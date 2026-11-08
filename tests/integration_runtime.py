"""Real Docker integration, using a temporary Shadowsocks node and no accounts.

Run explicitly: PYTHONPATH=windows python tests/integration_runtime.py --context NAME
It downloads/builds images and contacts the documented IP-check providers. Only
resources labeled with the generated instance ID are removed during cleanup.
"""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import secrets
import socket
import tempfile
import time
import urllib.request
import urllib.parse

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from enge_spx.engine import Engine, GATEWAY_IMAGE, OWNER
from enge_spx.nodes import parse_nodes
from enge_spx.state import Store, SPXError, atomic_json


def wait_lock(store):
    for _ in range(100):
        context = store.lock()
        try:
            context.__enter__()
            return context
        except SPXError:
            time.sleep(1)
    raise AssertionError("Could not acquire operation lock")


def execute(engine, container, code):
    return engine.docker.run("exec", container, "python3", "-c", code)


def run(context, output):
    records = []
    def passed(label):
        records.append(label)
        print("PASS", label, flush=True)
    with tempfile.TemporaryDirectory(prefix="spx-integration-") as temporary:
        base = Path(temporary)
        store = Store(base / "private")
        store.write("settings.json", {**store.settings(), "context": context})
        engine = Engine(store, lambda message: print(message, flush=True))
        node_name = engine.prefix + "-test-node"
        try:
            engine.install()
            passed("native gateway/work/browser images built")
            gateway_ip, _ = engine.networks()
            password = secrets.token_hex(16)
            node_config = {"log": {"level": "warn"}, "dns": {"servers": [{"type": "local", "tag": "local"}]}, "inbounds": [{"type": "shadowsocks", "listen": "0.0.0.0", "listen_port": 8443, "method": "aes-128-gcm", "password": password}], "outbounds": [{"type": "direct", "tag": "direct"}], "route": {"final": "direct", "default_domain_resolver": "local"}}
            node_dir = base / "node"
            node_dir.mkdir()
            atomic_json(node_dir / "config.json", node_config)
            engine.docker.run("run", "-d", "--name", node_name, "--network", engine.external, "--label", OWNER + "-fixture=" + store.instance, "--mount", f"type=bind,source={node_dir},target=/config,readonly", GATEWAY_IMAGE, "run", "-c", "/config/config.json")
            # The fixture is intentionally separate from Engine.managed(): a real
            # subscription server is external to this installation's lifecycle.
            obj = engine.docker.inspect("container", node_name)
            node_ip = obj["NetworkSettings"]["Networks"][engine.external]["IPAddress"]
            credentials = base64.urlsafe_b64encode(("aes-128-gcm:" + password).encode()).decode().rstrip("=")
            nodes, _ = parse_nodes(f"ss://{credentials}@{node_ip}:8443#Local-integration-node")
            engine.save_nodes(nodes)
            evidence = engine.check()
            assert evidence["direct_blocked"] is True
            passed("two exit sources agree; direct TCP egress blocked")
            engine.confirm()
            passed("review and fresh connection confirmation")
            # A fixture has no background guard: test lease failure deterministically.
            # Production start_guard is exercised by the UI/CLI; no credentials needed.
            project = base / "项目 with spaces"
            project.mkdir()
            project.chmod(0o777)
            with store.lock():
                state = engine.ready()
                viewer = engine._browser(state)
                worker, key = engine._project(str(project), state)
            browser = engine.inspect("browser")
            for _ in range(80):
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(viewer, timeout=2) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if not engine.inspect("browser")["State"]["Running"]:
                        raise AssertionError("Browser exited: " + engine.docker.run("logs", browser["Id"]))
                    time.sleep(1)
            else:
                raise AssertionError("Viewer did not become available")
            passed("Chromium/noVNC viewer starts on a loopback-only port")
            async def display_protocol():
                origin = urllib.parse.urlsplit(viewer)
                url = "ws://" + origin.netloc + "/websockify?token=" + state["browser_token"]
                async with connect(url, origin="http://" + origin.netloc, subprotocols=["binary"], proxy=None) as display:
                    banner = await asyncio.wait_for(display.recv(), 8)
                    assert isinstance(banner, bytes) and banner.startswith(b"RFB "), banner
                for url_suffix, requested_origin in (("invalid", "http://" + origin.netloc), (state["browser_token"], "https://untrusted.example")):
                    try:
                        async with connect("ws://" + origin.netloc + "/websockify?token=" + url_suffix, origin=requested_origin, subprotocols=["binary"], proxy=None):
                            raise AssertionError("Display accepted invalid authorization")
                    except InvalidStatus as error:
                        assert error.response.status_code == 403
            asyncio.run(display_protocol())
            passed("actual VNC banner received; bad token and foreign Origin rejected")
            for command, expected in (("codex", "codex-cli"), ("claude", "Claude Code")):
                version = engine.docker.run("exec", worker["Id"], command, "--version")
                assert expected in version, version
                passed(command + " executable: " + version)
            execute(engine, worker["Id"], f"from pathlib import Path; Path('/workspace/{key}/marker.txt').write_text('project'); Path('/home/workspace/.spx-test').write_text('home'); Path('/tmp/spx-layer').write_text('layer')")
            execute(engine, browser["Id"], "from pathlib import Path; Path('/home/workspace/.spx-browser-test').write_text('browser')")
            engine.docker.run("exec", "--env", "SPX_BROWSER_TOKEN=" + state["browser_token"], worker["Id"], "python3", "/opt/spx/open_browser.py", "https://example.com", timeout=45)
            passed("tool authorization URL opens inside shared Chromium")
            # Share a localhost callback listener between the actual two containers.
            execute(engine, worker["Id"], "import subprocess; subprocess.Popen(['python3','-m','http.server','1455','--bind','127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)")
            value = execute(engine, browser["Id"], "import urllib.request; print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:1455',timeout=5).status)")
            assert value == "200", value
            passed("browser can reach the tool's localhost OAuth callback")
            lock = wait_lock(store)
            try:
                store.write("runtime.json", {"phase": "stopped"})
                store.write("gateway/lease.json", {"expires": time.time() - 1})
            finally:
                lock.__exit__(None, None, None)
            for _ in range(15):
                if not engine.inspect("gateway")["State"]["Running"]:
                    break
                time.sleep(1)
            else:
                raise AssertionError("Gateway survived its expired lease")
            passed("gateway shuts itself down after the host lease expires")
            blocked = execute(engine, worker["Id"], "import socket; s=socket.socket(); s.settimeout(3)\ntry:\n s.connect(('1.1.1.1',443)); print('LEAK')\nexcept OSError:\n print('BLOCKED')")
            assert blocked == "BLOCKED", blocked
            passed("gateway failure does not enable direct egress")
            engine.stop()
            engine.check()
            engine.confirm()
            lock = wait_lock(store)
            try:
                state = engine.ready()
                engine._browser(state)
                resumed, _ = engine._project(str(project), state)
                assert resumed["Id"] == worker["Id"]
            finally:
                lock.__exit__(None, None, None)
            assert (project / "marker.txt").read_text() == "project"
            assert execute(engine, resumed["Id"], "from pathlib import Path; print(Path('/home/workspace/.spx-test').read_text()+Path('/tmp/spx-layer').read_text())") == "homelayer"
            assert execute(engine, engine.inspect("browser")["Id"], "from pathlib import Path; print(Path('/home/workspace/.spx-browser-test').read_text())") == "browser"
            passed("project files, tool home, writable layer and browser home survive stop/recheck")
            report = {"passed": records, "images": engine.image_ids(), "recipes": engine.recipes, "docker": engine.doctor(), "time": time.time()}
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        finally:
            try:
                engine.stop()
            except Exception:
                pass
            for identifier in engine.docker.run("ps", "-aq", "--filter", "label=" + OWNER + "=" + store.instance).splitlines():
                engine.owned(engine.docker.inspect("container", identifier))
                engine.docker.run("rm", "-f", identifier)
            fixture = engine.docker.inspect("container", node_name)
            if fixture:
                assert fixture["Config"]["Labels"].get(OWNER + "-fixture") == store.instance
                engine.docker.run("rm", "-f", fixture["Id"])
            for suffix in ("browser-home", "downloads", "tools-home"):
                try:
                    engine.docker.run("volume", "rm", engine.prefix + "-" + suffix)
                except SPXError:
                    pass
            for network in (engine.internal, engine.external):
                engine.docker.run("network", "rm", network)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="desktop-linux")
    parser.add_argument("--output", type=Path, default=Path("integration-results.json"))
    args = parser.parse_args()
    run(args.context, args.output)
