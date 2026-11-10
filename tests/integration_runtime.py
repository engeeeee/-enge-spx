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
from unittest.mock import patch

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from enge_spx.engine import Engine, GATEWAY_IMAGE, OWNER
from enge_spx.nodes import parse_nodes
from enge_spx.state import Store, SPXError, atomic_json
from enge_spx.browser_security import validate_container, validate_status


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
            # The real detached guard runs throughout; expiry is exercised later
            # by explicitly stopping its loop before revoking the lease.
            project = base / "项目 with spaces"
            project.mkdir()
            project.chmod(0o777)
            with store.lock(timeout=100):
                state = engine.ready()
                viewer = engine._browser(state)
                worker, key = engine._project(str(project), state)
            browser = engine.inspect("browser")
            validate_container(browser)
            sandbox = validate_status(json.loads(execute(engine, browser["Id"], "print(open('/tmp/spx-sandbox-status.json').read())")))
            passed("Chromium namespace/PID/network/seccomp sandbox and actual renderer kernel evidence verified")
            for role in ("gateway", "browser"):
                inspected = engine.inspect(role)
                metadata = json.dumps({key: inspected.get(key) for key in ("Args", "Path", "Config", "HostConfig", "Mounts")})
                assert password not in metadata and state["browser_token"] not in metadata
                assert not inspected["HostConfig"]["Privileged"] and not inspected["HostConfig"]["CapAdd"]
                assert not inspected["HostConfig"].get("PortBindings")
            gateway = engine.inspect("gateway")
            assert {item["Destination"] for item in gateway["Mounts"] if item["Type"] == "bind"} == {"/config/lease.jsonl"}
            assert execute(engine, gateway["Id"], "from pathlib import Path; print(Path('/tmp/spx/config.json').exists())") == "False"
            assert execute(engine, browser["Id"], "from pathlib import Path; print(Path('/dev/shm/spx/browser.json').exists())") == "False"
            passed("proxy passwords and browser token absent from Docker metadata; only public lease bind-mounted; RAM handoff files removed")
            isolation_code = '''import socket,struct,errno
for port in (5900,6099):
 s=socket.socket(); s.settimeout(2)
 assert s.connect_ex(('127.0.0.1',port)) != 0, 'Browser display exposed over TCP'
 s.close()
s=socket.socket(socket.AF_UNIX); s.settimeout(2)
try:
 s.connect('\\0/tmp/.X11-unix/X99')
 s.sendall(struct.pack('<BBHHHHH',ord('l'),0,11,0,0,0,0))
 assert s.recv(1024)[:1] != b'\\x01', 'X11 accepted a CLI peer without its private cookie'
except OSError as error:
 assert error.errno in (errno.ENOENT,errno.ECONNREFUSED,errno.EACCES), str(error)
finally: s.close()
print('DISPLAY_ISOLATED')'''
            assert execute(engine, worker["Id"], isolation_code) == "DISPLAY_ISOLATED"
            passed("CLI cannot access VNC TCP, X11 TCP or unauthenticated shared-namespace X11")
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
                for _ in range(2):
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
            passed("VNC display reconnects without restarting the browser; bad token and foreign Origin rejected")
            for command, expected in (("codex", "codex-cli"), ("claude", "Claude Code")):
                version = engine.docker.run("exec", worker["Id"], command, "--version")
                assert expected in version, version
                passed(command + " executable: " + version)
            execute(engine, worker["Id"], f"from pathlib import Path; Path('/workspace/{key}/marker.txt').write_text('project'); Path('/home/workspace/.spx-test').write_text('home'); Path('/tmp/spx-layer').write_text('layer')")
            execute(engine, browser["Id"], "from pathlib import Path; Path('/home/workspace/.spx-browser-test').write_text('browser')")
            engine.docker.run("exec", *engine.control_env(state), worker["Id"], "python3", "/opt/spx/open_browser.py", "https://example.com", timeout=45)
            passed("tool authorization URL opens inside shared Chromium")
            # Share a localhost callback listener between the actual two containers.
            execute(engine, worker["Id"], "import subprocess; subprocess.Popen(['python3','-m','http.server','1455','--bind','127.0.0.1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)")
            value = execute(engine, browser["Id"], "import urllib.request; print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:1455',timeout=5).status)")
            assert value == "200", value
            passed("browser can reach the tool's localhost OAuth callback")
            fonts = engine.docker.run("exec", browser["Id"], "fc-list", ":lang=zh", "family")
            assert not fonts.strip(), "Browser image still advertises Chinese system fonts: " + fonts
            passed("browser image has no Chinese system-font families")
            unicode_code = """import os,pty,subprocess,select,time
master,slave=pty.openpty()
text='中文输入与显示 — Claude Code / Codex'
p=subprocess.Popen(['python3','-c','value=input(); print(\"ROUNDTRIP:\"+value,flush=True)'],stdin=slave,stdout=slave,stderr=slave)
os.close(slave)
os.write(master,(text+'\\n').encode('utf-8'))
output=b''
deadline=time.monotonic()+5
try:
 while time.monotonic()<deadline:
  if select.select([master],[],[],.1)[0]:
   try: output+=os.read(master,65536)
   except OSError: break
  if ('ROUNDTRIP:'+text).encode('utf-8') in output: break
 assert ('ROUNDTRIP:'+text).encode('utf-8') in output,repr(output)
 assert p.wait(timeout=2)==0
 print('UTF8_PTY_OK')
finally:
 os.close(master)
 if p.poll() is None: p.kill(); p.wait()
"""
            assert execute(engine, worker["Id"], unicode_code) == "UTF8_PTY_OK"
            passed("Chinese input and output round-trip through the project container's real PTY")
            # Do not execute ready(), tool commands or shell input for longer
            # than one complete 180-second lease. Only the detached guard can
            # keep this already-open browser environment alive.
            first_heartbeat = store.read("runtime.json")["heartbeat"]
            deadline = time.monotonic() + 190
            while time.monotonic() < deadline:
                current = store.read("runtime.json")
                assert current.get("phase") == "ready", current.get("reason")
                time.sleep(2)
            current = store.read("runtime.json")
            assert current["heartbeat"] > first_heartbeat + 120, "Guard did not renew independently of shell activity"
            assert time.time() - current["heartbeat"] < 100
            assert all(engine.inspect(role)["State"]["Running"] for role in ("gateway", "session", "browser"))
            with opener.open(viewer, timeout=5) as response:
                assert response.status == 200
            passed("browser-only session survives 190 seconds without shell input; detached guard renews the lease")
            lock = wait_lock(store)
            try:
                engine.set_lease(time.time() - 1, store.read("runtime.json"))
                store.write("runtime.json", {"phase": "stopped"})
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
            # Exercise the actual data-directory migration against stopped Docker
            # resources. A gateway bind mount must follow the new path, while the
            # project container (including its writable layer) must stay intact.
            previous_home = store.home
            previous_gateway = engine.inspect("gateway")["Id"]
            previous_session = engine.inspect("session")["Id"]
            previous_images = engine.image_ids()
            (store.home / "cache").mkdir(exist_ok=True)
            (store.home / "cache/partial-download.part").write_bytes(b"resume fixture")
            with patch.dict("os.environ", {"LOCALAPPDATA": str(base / "launcher")}):
                engine.migrate_storage(base / "relocated data", lambda value: print("MIGRATE", value["message"], flush=True))
                assert Store().home == (base / "relocated data").resolve()
            store = Store(previous_home)
            engine = Engine(store, lambda message: print(message, flush=True))
            assert (store.home / "cache/partial-download.part").read_bytes() == b"resume fixture"
            assert not (previous_home / "cache/partial-download.part").exists()
            assert engine.image_ids() == previous_images
            engine.check()
            engine.confirm()
            lock = wait_lock(store)
            try:
                state = engine.ready()
                engine._browser(state)
                migrated, _ = engine._project(str(project), state)
                assert migrated["Id"] == worker["Id"]
                assert engine.inspect("session")["Id"] == previous_session
                gateway = engine.inspect("gateway")
                assert gateway["Id"] != previous_gateway
                mount = next(item for item in gateway["Mounts"] if item["Destination"] == "/config/lease.jsonl")
                assert Path(mount["Source"]).resolve() == (store.home / "gateway/lease.jsonl").resolve()
            finally:
                lock.__exit__(None, None, None)
            assert (project / "marker.txt").read_text() == "project"
            assert execute(engine, migrated["Id"], "from pathlib import Path; print(Path('/home/workspace/.spx-test').read_text()+Path('/tmp/spx-layer').read_text())") == "homelayer"
            assert execute(engine, engine.inspect("browser")["Id"], "from pathlib import Path; print(Path('/home/workspace/.spx-browser-test').read_text())") == "browser"
            passed("data relocation preserves project container, layer, accounts and browser; gateway uses new bind mount")
            report = {"passed": records, "images": engine.image_ids(), "recipes": engine.recipes, "docker": engine.doctor(), "time": time.time()}
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except Exception:
            # Only the browser supervisor's bounded, non-secret startup errors.
            browser = engine.inspect("browser")
            if browser:
                print("BROWSER STARTUP DIAGNOSTICS", engine.docker.redact(engine.docker.run("logs", "--tail", "35", browser["Id"])), flush=True)
            raise
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
