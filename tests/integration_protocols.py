"""Real local TLS/Reality/QUIC fixtures. No accounts, public services or TLS bypass.

Run with an official matching core: PYTHONPATH=src python tests/integration_protocols.py
--core /path/to/sing-box --output report.json. Docker runs this with network=none.
Only fixture servers have direct outbounds; every tested client uses the adapter.
"""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import socketserver
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid

from enge_spx.backends import DEFAULT_BACKEND
from enge_spx.nodes import normalize, uri_node


DOMAIN = "spx-target.invalid"
SNI = "proxy.spx.test"


def port(udp=False):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def receive(sock, length):
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise OSError("Fixture stream closed")
        data += chunk
    return data


def socks_address(sock, kind):
    if kind == 1:
        return socket.inet_ntoa(receive(sock, 4))
    if kind == 3:
        return receive(sock, receive(sock, 1)[0]).decode()
    if kind == 4:
        return socket.inet_ntop(socket.AF_INET6, receive(sock, 16))
    raise OSError("Bad SOCKS address type")


def socks_command(proxy_port, command, address, destination_port):
    sock = socket.create_connection(("127.0.0.1", proxy_port), 2.5)
    try:
        sock.settimeout(2.5)
        sock.sendall(b"\x05\x01\x00")
        if receive(sock, 2) != b"\x05\x00":
            raise OSError("SOCKS authentication failed")
        encoded = address.encode()
        sock.sendall(bytes((5, command, 0, 3, len(encoded))) + encoded + struct.pack("!H", destination_port))
        reply = receive(sock, 4)
        if reply[:3] != b"\x05\x00\x00":
            raise OSError("SOCKS connection rejected")
        host = socks_address(sock, reply[3])
        bound_port = struct.unpack("!H", receive(sock, 2))[0]
        return sock, host, bound_port
    except BaseException:
        sock.close()
        raise


def fetch(proxy_port, target_port, *, http=False):
    if http:
        sock = socket.create_connection(("127.0.0.1", proxy_port), 2.5)
        request = f"GET http://{DOMAIN}:{target_port}/ HTTP/1.1\r\nHost: {DOMAIN}\r\nConnection: close\r\n\r\n"
    else:
        sock, _, _ = socks_command(proxy_port, 1, DOMAIN, target_port)
        request = f"GET / HTTP/1.1\r\nHost: {DOMAIN}\r\nConnection: close\r\n\r\n"
    with sock:
        sock.settimeout(2.5)
        sock.sendall(request.encode())
        response = b""
        while len(response) < 16384:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        header, body = response.split(b"\r\n\r\n", 1)
        if b" 200 " not in header.split(b"\r\n")[0]:
            raise OSError("Fixture HTTP request failed")
        return json.loads(body)


def udp_echo(proxy_port, target_port):
    control, host, relay_port = socks_command(proxy_port, 3, "0.0.0.0", 0)
    with control, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.5)
        payload = secrets.token_bytes(4096)
        packet = b"\x00\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", target_port) + payload
        sock.sendto(packet, ("127.0.0.1" if host == "0.0.0.0" else host, relay_port))
        data, _ = sock.recvfrom(8192)
        assert data[0:4] == b"\x00\x00\x00\x01" and data[10:] == payload, "QUIC UDP echo mismatch"


class Fixtures:
    def __init__(self, folder):
        self.folder = folder
        self.hits, self.udp_sources = [], []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                owner.hits.append(self.client_address[0])
                body = json.dumps({"peer": self.client_address[0]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.cert, self.key = folder / "fixture.pem", folder / "fixture.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(self.key), "-out", str(self.cert), "-days", "1", "-subj", "/CN=" + SNI, "-addext", "subjectAltName=DNS:" + SNI], check=True, capture_output=True)
        self.key.chmod(0o600)
        self.tls = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.set_alpn_protocols(["h2", "http/1.1"])
        context.load_cert_chain(self.cert, self.key)
        self.tls.socket = context.wrap_socket(self.tls.socket, server_side=True)
        class UDP(socketserver.BaseRequestHandler):
            def handle(self):
                owner.udp_sources.append(self.client_address[0])
                self.request[1].sendto(self.request[0], self.client_address)
        self.udp = socketserver.ThreadingUDPServer(("127.0.0.1", 0), UDP)
        for service in (self.http, self.tls, self.udp):
            threading.Thread(target=service.serve_forever, daemon=True).start()

    def close(self):
        for service in (self.http, self.tls, self.udp):
            service.shutdown()
            service.server_close()


class Core:
    def __init__(self, binary, folder, name, config):
        self.process = None
        self.path = folder / (name + ".json")
        self.path.write_text(json.dumps(config))
        self.path.chmod(0o600)
        checked = subprocess.run([binary, "check", "-c", str(self.path)], capture_output=True, text=True)
        if checked.returncode:
            raise RuntimeError(name + " config rejected: " + checked.stderr[-2000:])
        self.log_path = folder / (name + ".log")
        self.log = self.log_path.open("wb")
        self.process = subprocess.Popen([binary, "run", "-c", str(self.path)], stdout=self.log, stderr=self.log)
        time.sleep(.15)
        if self.process.poll() is not None:
            self.close()
            raise RuntimeError(name + " did not start: " + self.log_path.read_text()[-2000:])

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.log.close()


class UDPGate:
    """Test-only QUIC packet loss injection; no firewall or host setting changes."""
    def __init__(self, destination_port):
        self.enabled, self.stopped, self.peers = True, threading.Event(), {}
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(("127.0.0.1", 0))
        self.front.settimeout(.2)
        self.port, self.destination_port = self.front.getsockname()[1], destination_port
        threading.Thread(target=self.forward, daemon=True).start()

    def backward(self, sock, peer):
        while not self.stopped.is_set():
            try:
                data = sock.recv(65535)
                if self.enabled:
                    self.front.sendto(data, peer)
            except socket.timeout:
                continue
            except OSError:
                return

    def forward(self):
        while not self.stopped.is_set():
            try:
                data, peer = self.front.recvfrom(65535)
                if not self.enabled:
                    continue
                if peer not in self.peers:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.connect(("127.0.0.1", self.destination_port))
                    sock.settimeout(.2)
                    self.peers[peer] = sock
                    threading.Thread(target=self.backward, args=(sock, peer), daemon=True).start()
                self.peers[peer].send(data)
            except socket.timeout:
                continue
            except OSError:
                return

    def close(self):
        self.stopped.set()
        self.front.close()
        for sock in tuple(self.peers.values()):
            sock.close()


def rejected_request(proxy_port, target, fixtures, reason):
    count = len(fixtures.hits)
    try:
        fetch(proxy_port, target)
    except (OSError, ValueError):
        pass
    else:
        raise AssertionError(reason + " unexpectedly reached the target")
    assert len(fixtures.hits) == count, reason + " caused a bypass"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    version = subprocess.check_output([args.core, "version"], text=True)
    assert "1.14.3" in version and "with_quic" in version and "with_utls" in version
    report = {"schema": 1, "core": version, "network": "local synthetic fixtures", "tls_verification_disabled": False, "passed": records}
    def passed(label):
        records.append(label)
        print("PASS", label, flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="spx-protocol-") as temporary, ExitStack() as cleanup:
            folder = Path(temporary)
            fixtures = Fixtures(folder)
            cleanup.callback(fixtures.close)
            certificate = fixtures.cert.read_text()
            server_tls = {"enabled": True, "certificate_path": str(fixtures.cert), "key_path": str(fixtures.key)}
            client_tls = {"enabled": True, "server_name": SNI, "certificate": [certificate]}
            identity, password = str(uuid.uuid4()), secrets.token_hex(16)
            keypair = subprocess.check_output([args.core, "generate", "reality-keypair"], text=True)
            keys = dict(line.split(": ", 1) for line in keypair.strip().splitlines())
            inbounds, cases, landing = [], [], []
            variants = [(kind, transport) for kind in ("vless", "trojan", "vmess") for transport in (None, "ws", "grpc")]
            variants += [("vless", "reality"), ("shadowsocks", None), ("socks", None), ("http", None), ("http", "tls"), ("hysteria2", None), ("hysteria2", "salamander")]
            for kind, transport in variants:
                name = kind + "-" + (transport or "tcp")
                inbound = {"type": kind, "tag": name, "listen": "127.0.0.1", "listen_port": port(kind == "hysteria2")}
                outbound = {"type": kind, "server": "127.0.0.1", "server_port": inbound["listen_port"]}
                if kind in ("socks", "http"):
                    inbound["users"] = [{"username": "fixture", "password": password}]
                    outbound.update(username="fixture", password=password)
                    if kind == "socks":
                        outbound["version"] = "5"
                    if transport == "tls":
                        inbound["tls"], outbound["tls"] = deepcopy(server_tls), deepcopy(client_tls)
                elif kind == "shadowsocks":
                    inbound.update(method="aes-128-gcm", password=password)
                    outbound.update(method="aes-128-gcm", password=password)
                else:
                    user = {"name": "fixture", "uuid" if kind in ("vless", "vmess") else "password": identity if kind in ("vless", "vmess") else password}
                    inbound["users"] = [user]
                    outbound.update({key: val for key, val in user.items() if key != "name"})
                    inbound["tls"], outbound["tls"] = deepcopy(server_tls), deepcopy(client_tls)
                    if kind == "vmess":
                        outbound["security"] = "auto"
                    if transport in ("ws", "grpc"):
                        value = {"type": "ws", "path": "/fixture"} if transport == "ws" else {"type": "grpc", "service_name": "fixture"}
                        inbound["transport"], outbound["transport"] = deepcopy(value), value
                    elif transport == "reality":
                        inbound["users"][0]["flow"] = outbound["flow"] = "xtls-rprx-vision"
                        inbound["tls"] = {"enabled": True, "server_name": SNI, "reality": {"enabled": True, "handshake": {"server": "127.0.0.1", "server_port": fixtures.tls.server_port}, "private_key": keys["PrivateKey"], "short_id": ["0123456789abcdef"]}}
                        outbound["tls"] = {"enabled": True, "server_name": SNI, "reality": {"enabled": True, "public_key": keys["PublicKey"], "short_id": "0123456789abcdef"}, "utls": {"enabled": True, "fingerprint": "chrome"}}
                    elif transport == "salamander":
                        inbound["obfs"] = outbound["obfs"] = {"type": "salamander", "password": secrets.token_hex(16)}
                node = normalize(outbound)
                # Exercise the actual Reality URI conversion as well as JSON.
                if transport == "reality":
                    node = uri_node(f"vless://{identity}@127.0.0.1:{inbound['listen_port']}?security=reality&sni={SNI}&pbk={keys['PublicKey']}&sid=0123456789abcdef&fp=chrome&flow=xtls-rprx-vision")
                cases.append((name, node))
                if kind in ("socks", "http"):
                    landing.append((name, node))
                inbounds.append(inbound)
            dns = {"servers": [{"type": "hosts", "tag": "fixture-dns", "predefined": {DOMAIN: ["127.0.0.1"], "spx-landing.invalid": ["127.0.0.1"]}}]}
            landing_names = {name for name, _ in landing}
            def fixture_server(entries, address):
                return {"log": {"level": "error"}, "dns": dns, "inbounds": entries, "outbounds": [{"type": "direct", "tag": "fixture-only", "inet4_bind_address": address, "domain_resolver": "fixture-dns"}], "route": {"final": "fixture-only"}}
            server_config = fixture_server([item for item in inbounds if item["tag"] not in landing_names], "127.0.0.2")
            server = Core(args.core, folder, "servers", server_config)
            cleanup.callback(server.close)
            landing_server = Core(args.core, folder, "landings", fixture_server([item for item in inbounds if item["tag"] in landing_names], "127.0.0.3"))
            cleanup.callback(landing_server.close)
            target = fixtures.http.server_port
            for index, (name, node) in enumerate(cases):
                config = DEFAULT_BACKEND.gateway_config([node["outbound"]], "127.0.0.1", False)
                proxy_port = config["inbounds"][0]["listen_port"] = port()
                client = Core(args.core, folder, "client-" + str(index), config)
                try:
                    expected = "127.0.0.3" if name in landing_names else "127.0.0.2"
                    assert fetch(proxy_port, target)["peer"] == expected
                    assert fetch(proxy_port, target, http=True)["peer"] == expected
                    passed(name + ": SOCKS/HTTP and remote-only DNS resolution")
                    if node["outbound"]["type"] == "hysteria2":
                        udp_echo(proxy_port, fixtures.udp.server_address[1])
                        assert fixtures.udp_sources[-1] == "127.0.0.2"
                        passed(name + ": real QUIC TCP and fragmented UDP payload")
                finally:
                    client.close()
            for index, (name, node) in enumerate(cases):
                if name in landing_names:
                    continue
                for landing_index, (landing_name, landing_node) in enumerate(landing):
                    selected = {**deepcopy(landing_node["outbound"]), "server": "spx-landing.invalid", "detour": "spx-line"}
                    line = {**deepcopy(node["outbound"]), "tag": "spx-line"}
                    config = DEFAULT_BACKEND.gateway_config([selected, line], "127.0.0.1", True)
                    final_port = config["inbounds"][0]["listen_port"] = port()
                    line_port = config["inbounds"][1]["listen_port"] = port()
                    client = Core(args.core, folder, f"chain-{index}-{landing_index}", config)
                    try:
                        assert fetch(line_port, target, http=True)["peer"] == "127.0.0.2"
                        assert fetch(final_port, target)["peer"] == "127.0.0.3"
                        passed(name + " -> " + landing_name + ": independent line/final exits and remote landing DNS")
                    finally:
                        client.close()
            # Certificate authentication is not bypassed by any new TLS transport.
            for index, (name, node) in enumerate(cases):
                value = deepcopy(node["outbound"])
                if not value.get("tls") or value["tls"].get("reality"):
                    continue
                value["tls"].pop("certificate", None)
                config = DEFAULT_BACKEND.gateway_config([value], "127.0.0.1", False)
                proxy_port = config["inbounds"][0]["listen_port"] = port()
                client = Core(args.core, folder, "bad-ca-" + str(index), config)
                try:
                    rejected_request(proxy_port, target, fixtures, name + " untrusted CA")
                    passed(name + ": certificate error fails closed")
                finally:
                    client.close()
            reality = next(node for name, node in cases if name == "vless-reality")
            for field, replacement in (("short_id", "ffffffffffffffff"), ("public_key", keys["PrivateKey"])):
                value = deepcopy(reality["outbound"])
                value["tls"]["reality"][field] = replacement
                config = DEFAULT_BACKEND.gateway_config([value], "127.0.0.1", False)
                proxy_port = config["inbounds"][0]["listen_port"] = port()
                client = Core(args.core, folder, "bad-reality-" + field, config)
                try:
                    rejected_request(proxy_port, target, fixtures, "Reality " + field)
                    passed("Reality wrong " + field + " fails closed")
                finally:
                    client.close()
            hy2 = next(node for name, node in cases if name == "hysteria2-tcp")
            gate = UDPGate(hy2["outbound"]["server_port"])
            cleanup.callback(gate.close)
            config = DEFAULT_BACKEND.gateway_config([{**deepcopy(hy2["outbound"]), "server_port": gate.port}], "127.0.0.1", False)
            proxy_port = config["inbounds"][0]["listen_port"] = port()
            client = Core(args.core, folder, "udp-failure", config)
            try:
                assert fetch(proxy_port, target)["peer"] == "127.0.0.2"
                udp_echo(proxy_port, fixtures.udp.server_address[1])
                gate.enabled = False
                rejected_request(proxy_port, target, fixtures, "QUIC UDP path loss")
                passed("Hysteria2 established QUIC loses all UDP packets: no TCP or DIRECT fallback")
            finally:
                client.close()
            server.close()
            # The landing is deliberately still alive. Killing the first hop
            # must not silently connect the landing or target from the gateway.
            for index, (name, node) in enumerate(cases):
                if name in landing_names:
                    continue
                selected = {**deepcopy(landing[0][1]["outbound"]), "detour": "spx-line"}
                line = {**deepcopy(node["outbound"]), "tag": "spx-line"}
                config = DEFAULT_BACKEND.gateway_config([selected, line], "127.0.0.1", True)
                proxy_port = config["inbounds"][0]["listen_port"] = port()
                config["inbounds"][1]["listen_port"] = port()
                client = Core(args.core, folder, "dead-line-" + str(index), config)
                try:
                    rejected_request(proxy_port, target, fixtures, name + " dead first hop")
                    passed(name + ": line failure cannot bypass to a live landing or DIRECT")
                finally:
                    client.close()
            report["success"] = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
