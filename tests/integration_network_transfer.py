"""Real TLS and sing-box final-chain measurements in a network-none test image.

The target is a local TLS fixture with a temporary trusted CA. There is no TLS
bypass, public traffic, AI account or host listener. Production target/config
handling is executed unchanged in a separate guest Python process.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from enge_spx.backends import DEFAULT_BACKEND
from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.network_performance import evidence, PAYLOAD_BYTES
from integration_protocols import Core


class Fixtures:
    def __init__(self, folder):
        self.mode = "ok"
        self.context_index = 0
        self.sizes, self.connects = [], []
        self.password = "synthetic-network-fixture-password"
        self.certs = []
        for name, host in (("valid", "speed.cloudflare.com"), ("wrong-name", "different.spx.test")):
            cert, key = folder / (name + ".pem"), folder / (name + ".key")
            subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=" + host, "-addext", "subjectAltName=DNS:" + host], check=True, capture_output=True)
            key.chmod(0o600)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            context.set_alpn_protocols(["http/1.1"])
            self.certs.append((cert, context))
        def choose_context(stream, name, context):
            assert name == "speed.cloudflare.com", "Guest omitted the expected target SNI"
            stream.context = self.certs[self.context_index][1]
        self.certs[0][1].set_servername_callback(choose_context)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                size = int(parse_qs(urlsplit(self.path).query)["bytes"][0])
                owner.sizes.append(size)
                try:
                    if owner.mode == "slow":
                        for byte in b"HTTP/1.1 200 OK\r\nX-Slow: drip-fed-header-cannot-reset-the-total-deadline\r\n\r\n":
                            self.wfile.write(bytes((byte,))); self.wfile.flush(); time.sleep(.2)
                        return
                    self.send_response(302 if owner.mode == "redirect" else 200)
                    if owner.mode == "redirect":
                        self.send_header("Location", "https://must-not-follow.spx.test/private")
                    if owner.mode != "oversized":
                        self.send_header("Content-Length", str(size + 1 if owner.mode == "wrong-size" else size))
                    if owner.mode == "encoded":
                        self.send_header("Content-Encoding", "gzip")
                    self.end_headers()
                    self.wfile.write(b"x" * (size + 64 if owner.mode == "oversized" else size))
                except (OSError, ssl.SSLError):
                    pass
        self.tls = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.tls.daemon_threads = True
        self.tls.socket = self.certs[0][1].wrap_socket(self.tls.socket, server_side=True)
        class Proxy(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                header = b""
                try:
                    while b"\r\n\r\n" not in header and len(header) < 16384:
                        data = self.request.recv(1)
                        if not data:
                            return
                        header += data
                    first = header.split(b"\r\n", 1)[0]
                    owner.connects.append(first.decode("ascii"))
                    if first != b"CONNECT speed.cloudflare.com:443 HTTP/1.1" and first != b"CONNECT speed.cloudflare.com:443 HTTP/1.0":
                        self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n"); return
                    lines = {k.strip().lower(): v.strip() for line in header.split(b"\r\n")[1:] if b":" in line for k, v in [line.split(b":", 1)]}
                    if lines.get(b"proxy-authorization") != b"Basic " + base64.b64encode(("fixture:" + owner.password).encode()):
                        self.request.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"); return
                    with socket.create_connection(self.server.target, 3) as upstream:
                        upstream.settimeout(3)
                        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                        until = time.monotonic() + 22
                        while time.monotonic() < until:
                            ready, _, _ = select.select([self.request, upstream], [], [], .2)
                            for origin in ready:
                                data = origin.recv(16384)
                                if not data:
                                    return
                                (upstream if origin is self.request else self.request).sendall(data)
                except OSError:
                    pass
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        self.proxy = Server(("127.0.0.1", 0), Proxy)
        self.proxy.target = self.tls.server_address
        for service in (self.tls, self.proxy):
            threading.Thread(target=service.serve_forever, daemon=True).start()
        self.proxy_closed = False

    def stop_proxy(self):
        if not self.proxy_closed:
            self.proxy.shutdown(); self.proxy.server_close(); self.proxy_closed = True

    def close(self):
        self.stop_proxy()
        self.tls.shutdown(); self.tls.server_close()


def run(binary, output):
    passed = []
    def success(message):
        passed.append(message); print("PASS", message, flush=True)
    with tempfile.TemporaryDirectory(prefix="spx-network-transfer-") as folder:
        base = Path(folder)
        fixture = Fixtures(base)
        config = DEFAULT_BACKEND.gateway_config([{"tag": "selected", "type": "http", "server": "127.0.0.1", "server_port": fixture.proxy.server_address[1], "username": "fixture", "password": fixture.password}], "127.0.0.1", False)
        assert [value["type"] for value in config["outbounds"]] == ["http"]
        core = Core(binary, base, "measurement-client", config)
        code = PACKAGE_RESOURCES / "checks/network_probe.py"
        try:
            for _ in range(30):
                try:
                    with socket.create_connection(("127.0.0.1", 2080), .1):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError("Fixture adapter did not start")
            def measure(cert=None):
                env = {**os.environ, "SSL_CERT_FILE": str(cert or fixture.certs[0][0]), "NO_PROXY": "*", "no_proxy": "*", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9"}
                started = time.monotonic()
                result = subprocess.run([sys.executable, str(code)], input=json.dumps({"proxy": "http://127.0.0.1:2080"}), capture_output=True, text=True, env=env, timeout=22)
                assert result.returncode == 0, "Guest measurement failed without a report"
                assert fixture.password not in result.stdout + result.stderr
                value = evidence(json.loads(result.stdout))
                return value, time.monotonic() - started

            data, _ = measure()
            assert data["status"] == "measured" and data["download"]["request_mbps"] > 0
            assert fixture.sizes == [1024, 1024, 1048576] and sum(fixture.sizes) == PAYLOAD_BYTES
            assert len(fixture.connects) == 3
            success("real production guest transfers exact bounded payload through the sing-box adapter and authenticated landing; NO_PROXY/HTTPS_PROXY cannot bypass")
            hits = len(fixture.sizes)
            data, _ = measure(fixture.certs[1][0])
            assert all(row.get("error_code") == "tls_certificate_error" for row in data["samples"])
            assert len(fixture.sizes) == hits
            success("untrusted CA fails TLS before any HTTP body request and never retries direct")
            fixture.context_index = 1
            data, _ = measure(fixture.certs[1][0])
            assert all(row.get("error_code") == "tls_certificate_error" for row in data["samples"])
            assert len(fixture.sizes) == hits
            fixture.context_index = 0
            success("trusted certificate with wrong hostname is rejected; SNI/name verification remains enabled")
            for mode in ("redirect", "wrong-size", "encoded", "oversized"):
                fixture.mode = mode
                count = len(fixture.connects)
                data, _ = measure()
                assert data["status"] == "partial"
                assert all(row.get("error_code") == "response_rejected" for row in data["samples"])
                assert all(row["bytes_received"] <= row["requested_bytes"] + 1 for row in data["samples"])
                assert len(fixture.connects) == count + 3
                assert data["download"]["request_mbps"] is None
                success("real " + mode + " response rejected without another target, unbounded read or fake zero-speed success")
            fixture.mode = "slow"
            data, elapsed = measure()
            assert elapsed < 22 and data["status"] == "partial"
            assert all(row.get("error_code") in ("timeout", "time_budget") for row in data["samples"])
            success("drip-fed response headers cannot extend the whole guest budget; interrupted sockets close and incomplete samples stay unavailable")
            fixture.mode = "ok"
            fixture.stop_proxy()
            hits = len(fixture.sizes)
            data, _ = measure()
            assert data["status"] == "partial" and len(fixture.sizes) == hits
            assert all(row["result"] == "failed" for row in data["samples"])
            success("dead landing cannot reach the still-healthy TLS target or fall back to a different path")
        finally:
            core.close(); fixture.close()
    report = {"schema": 1, "scope": "real local TLS/CONNECT via production sing-box adapter in network-none container; temporary trusted CA, no public endpoint or real AI/physical Windows acceptance", "passed": passed}
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.core, args.output)
