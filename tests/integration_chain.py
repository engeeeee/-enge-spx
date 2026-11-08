"""A real loopback line -> authenticated SOCKS landing -> internet integration."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import select
import socket
import tempfile
import threading
import time

from enge_spx.engine import Engine, GATEWAY_IMAGE
from enge_spx.nodes import uri_node
from enge_spx.proxy import relay_config
from enge_spx.line_security import LINE_CHECK_CODE
from enge_spx.state import Store, SPXError, atomic_json


def run(context):
    with tempfile.TemporaryDirectory(prefix="spx-chain-") as directory:
        root = Path(directory)
        store = Store(root / "private")
        store.write("settings.json", {**store.settings(), "context": context})
        engine = Engine(store, lambda text: None)
        engine.start_guard = lambda: None  # Check line loss deterministically below.
        engine.install()
        engine.networks()
        name = engine.prefix + "-fixture"
        line_name = engine.prefix + "-encrypted-line"
        username, password = "landing", secrets.token_hex(12)
        node_dir = root / "node"
        node_dir.mkdir()
        config = {"log": {"level": "error"}, "dns": {"servers": [{"type": "local", "tag": "local"}]}, "inbounds": [{"type": "mixed", "listen": "0.0.0.0", "listen_port": 8443, "users": [{"username": username, "password": password}]}], "outbounds": [{"type": "direct", "tag": "direct"}], "route": {"final": "direct", "default_domain_resolver": "local"}}
        atomic_json(node_dir / "config.json", config)
        engine.docker.run("run", "-d", "--name", name, "--network", engine.external, "--mount", f"type=bind,source={node_dir},target=/config,readonly", GATEWAY_IMAGE, "run", "-c", "/config/config.json")
        ip = engine.docker.inspect("container", name)["NetworkSettings"]["Networks"][engine.external]["IPAddress"]
        line_password = secrets.token_hex(12)
        seen = []
        class Line(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_CONNECT(self):
                expected = "Basic " + base64.b64encode(("line:" + line_password).encode()).decode()
                allowed = {ip + ":8443", "landing.spx.invalid:8443", "api.ipify.org:443", "checkip.amazonaws.com:443"}
                if self.headers.get("Proxy-Authorization") != expected or self.path not in allowed:
                    self.send_error(403)
                    return
                landing_connection = self.path in (ip + ":8443", "landing.spx.invalid:8443")
                if landing_connection:
                    seen.append(self.path)
                self.close_connection = True
                destination = (ip, 8443) if landing_connection else (self.path.rsplit(":", 1)[0], 443)
                with socket.create_connection(destination, timeout=5) as target:
                    self.send_response(200, "Connection established")
                    self.end_headers()
                    self.wfile.flush()
                    target.settimeout(None)
                    sockets = [target, self.connection]
                    while True:
                        ready, _, _ = select.select(sockets, [], [], 20)
                        if not ready:
                            return
                        for incoming in ready:
                            data = incoming.recv(65536)
                            if not data:
                                return
                            (target if incoming is self.connection else self.connection).sendall(data)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Line)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            # Exercise both landing forms over the same local HTTP line proxy.
            for scheme in ("socks5", "http"):
                # Only the proxy knows this name; host DNS must not resolve it.
                node = uri_node(f"{scheme}://{username}:{password}@landing.spx.invalid:8443")
                engine.save_nodes([node])
                middle = relay_config(True, f"http://line:{line_password}@127.0.0.1:{server.server_port}")
                engine.save_settings(node["id"], store.settings()["timezone"], context, middle)
                evidence = engine.check()
                assert evidence["direct_blocked"]
                assert evidence["line_ip"] and evidence["line_mode"] == "local"
                engine.confirm()
                assert seen, "The line proxy did not carry landing connections"
                print("PASS loopback HTTP line -> authenticated " + scheme.upper() + " landing -> verified exit", flush=True)
            # A bad line pin must stop before any request reaches the landing,
            # even though the landing itself is still available.
            wrong_ip = "1.1.1.1" if evidence["line_ip"] != "1.1.1.1" else "8.8.8.8"
            engine.save_settings(node["id"], store.settings()["timezone"], context, {**middle, "expected_ip": wrong_ip})
            before = len(seen)
            try:
                engine.check()
                raise AssertionError("Mismatched line pin was accepted")
            except SPXError:
                pass
            assert len(seen) == before
            assert store.read("runtime.json")["phase"] == "stopped"
            assert "前置线路" in store.read("runtime.json")["reason"]
            print("PASS wrong first-hop exit blocks before contacting an unchanged landing", flush=True)
            engine.save_settings(node["id"], store.settings()["timezone"], context, middle)
            engine.check()
            engine.confirm()
            with store.lock():
                state = store.read("runtime.json")
                state["evidence"]["line_ip"] = wrong_ip
                store.write("runtime.json", state)
                try:
                    engine.ready()
                    raise AssertionError("Changed line exit was accepted")
                except SPXError:
                    pass
            assert store.read("runtime.json")["phase"] == "stopped"
            print("PASS line-exit change stops a confirmed environment with an unchanged landing", flush=True)
            engine.check()
            engine.confirm()
            # Break the local line and verify that an established environment locks.
            server.shutdown()
            server.server_close()
            with store.lock():
                try:
                    engine.ready()
                except Exception:
                    pass
            assert store.read("runtime.json")["phase"] == "stopped"
            print("PASS line failure stops the environment without a direct fallback", flush=True)

            # Fixed encrypted first hop, independent of the user's v2ray rules.
            line_dir = root / "encrypted-line"
            line_dir.mkdir()
            ss_password = secrets.token_hex(16)
            line_config = {"log": {"level": "error"}, "dns": {"servers": [{"type": "local", "tag": "local"}]}, "inbounds": [{"type": "shadowsocks", "listen": "0.0.0.0", "listen_port": 8444, "method": "aes-128-gcm", "password": ss_password}], "outbounds": [{"type": "direct", "tag": "fixture-direct"}], "route": {"final": "fixture-direct", "default_domain_resolver": "local"}}
            atomic_json(line_dir / "config.json", line_config)
            engine.docker.run("run", "-d", "--name", line_name, "--network", "name=" + engine.external + ",gw-priority=1", "--add-host", "landing.spx.invalid:" + ip, "--mount", f"type=bind,source={line_dir},target=/config,readonly", GATEWAY_IMAGE, "run", "-c", "/config/config.json")
            engine.docker.run("network", "connect", engine.internal, line_name)
            line_ip = engine.docker.inspect("container", line_name)["NetworkSettings"]["Networks"][engine.internal]["IPAddress"]
            credentials = base64.urlsafe_b64encode(("aes-128-gcm:" + ss_password).encode()).decode().rstrip("=")
            line_node = uri_node(f"ss://{credentials}@{line_ip}:8444#Encrypted-first-hop")
            landing = uri_node(f"socks5://{username}:{password}@landing.spx.invalid:8443")
            engine.save_nodes([landing, line_node])
            secured = relay_config(True, "", False, "managed", line_node["id"])
            engine.save_settings(landing["id"], store.settings()["timezone"], context, secured)
            evidence = engine.check()
            assert evidence["direct_blocked"] and evidence["line_mode"] == "managed"
            engine.confirm()
            state = store.read("runtime.json")
            assert state["forward_target"] is None
            configuration = store.read("gateway/config.json")
            assert all(outbound["type"] not in ("direct", "selector", "urltest") for outbound in configuration["outbounds"])
            assert configuration["outbounds"][0]["server"] == "landing.spx.invalid"
            gateway_ip = engine.docker.inspect("container", state["gateway"])["NetworkSettings"]["Networks"][engine.internal]["IPAddress"]
            code = f"import socket\ns=socket.socket();s.settimeout(2)\ntry:\n s.connect(({gateway_ip!r},2082));print('BYPASS')\nexcept OSError:\n print('BLOCKED')"
            result = engine.docker.run("run", "--rm", "--network", "container:" + state["session"], "--cap-drop", "ALL", engine.image_ids()["work"], "python3", "-c", code)
            assert result == "BLOCKED"
            print("PASS managed encrypted line -> remote-resolved SOCKS landing; diagnostic listener cannot bypass landing", flush=True)
            # With no gateway Internet route, only the encrypted line peer on the
            # internal bridge can reach the providers. Poisoned NO_PROXY must not
            # bypass the explicit diagnostic proxy and break this test.
            engine.docker.run("network", "disconnect", engine.external, state["gateway"])
            try:
                direct = "import socket\ns=socket.socket();s.settimeout(2)\ntry:\n s.connect(('1.1.1.1',443));print('LEAK')\nexcept OSError:\n print('BLOCKED')"
                assert engine.docker.run("exec", state["gateway"], "python3", "-c", direct) == "BLOCKED"
                poisoned = engine.docker.run("exec", "--env", "NO_PROXY=*", "--env", "no_proxy=*", "--env", "HTTPS_PROXY=http://127.0.0.1:9", state["gateway"], "python3", "-c", LINE_CHECK_CODE, timeout=30)
                assert json.loads(poisoned)["ip"] == evidence["line_ip"]
            finally:
                engine.docker.run("network", "connect", "--gw-priority", "1", engine.external, state["gateway"])
            print("PASS poisoned NO_PROXY cannot bypass diagnostics; line check succeeds with gateway direct Internet blocked", flush=True)
            # Landing remains alive and reachable from the external bridge.
            # Even the final probe itself must fail if the first hop disappears.
            engine.docker.run("stop", "--time", "2", line_name)
            assert engine.docker.inspect("container", name)["State"]["Running"]
            try:
                engine.probe(state)
                raise AssertionError("Managed first hop silently fell back to the landing")
            except SPXError:
                pass
            with store.lock():
                try:
                    engine.ready()
                    raise AssertionError("Failed managed line was accepted")
                except SPXError:
                    pass
            assert store.read("runtime.json")["phase"] == "stopped"
            print("PASS managed line failure cannot fall back to a live landing or direct Internet", flush=True)
        except Exception:
            print('Line proxy connections:',len(seen),flush=True)
            for role in ("gateway", "session"):
                item = engine.inspect(role)
                if item:
                    print(engine.docker.run("logs", "--tail", "20", item["Id"]), flush=True)
            line_fixture = engine.docker.inspect("container", line_name)
            if line_fixture:
                print(engine.docker.run("logs", "--tail", "20", line_fixture["Id"]), flush=True)
            log = store.home / "forward.log"
            if log.exists():
                print(log.read_text()[-4000:], flush=True)
            guest_log = store.home / "forward-guest.log"
            if guest_log.exists():
                print(guest_log.read_text()[-4000:], flush=True)
            raise
        finally:
            engine.stop()
            for identifier in engine.managed():
                engine.docker.run("rm", "-f", identifier)
            engine.docker.run("rm", "-f", name)
            if engine.docker.inspect("container", line_name):
                engine.docker.run("rm", "-f", line_name)
            for network in (engine.internal, engine.external):
                engine.docker.run("network", "rm", network)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="default")
    run(parser.parse_args().context)
