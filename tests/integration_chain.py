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
from enge_spx.state import Store, atomic_json


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
                if self.headers.get("Proxy-Authorization") != expected or self.path != ip + ":8443":
                    self.send_error(403)
                    return
                seen.append(self.path)
                self.close_connection = True
                with socket.create_connection((ip, 8443), timeout=5) as target:
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
                node = uri_node(f"{scheme}://{username}:{password}@{ip}:8443")
                engine.save_nodes([node])
                middle = relay_config(True, f"http://line:{line_password}@127.0.0.1:{server.server_port}")
                engine.save_settings(node["id"], store.settings()["timezone"], context, middle)
                evidence = engine.check()
                assert evidence["direct_blocked"]
                engine.confirm()
                assert seen, "The line proxy did not carry landing connections"
                print("PASS loopback HTTP line -> authenticated " + scheme.upper() + " landing -> verified exit", flush=True)
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
        except Exception:
            print('Line proxy connections:',len(seen),flush=True)
            for role in ("gateway", "session"):
                item = engine.inspect(role)
                if item:
                    print(engine.docker.run("logs", "--tail", "20", item["Id"]), flush=True)
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
            for network in (engine.internal, engine.external):
                engine.docker.run("network", "rm", network)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="default")
    run(parser.parse_args().context)
