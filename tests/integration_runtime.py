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


LOGIN_FIXTURE = '''from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  import re,urllib.parse
  nonce=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('fixture',[''])[0]
  if re.fullmatch('[a-f0-9]{32}',nonce) is None:
   self.send_error(404);return
  prior='spx_fixture=persistent' in self.headers.get('Cookie','')
  html="<script>const previous=localStorage.getItem('spx_fixture');localStorage.setItem('spx_fixture','persistent');fetch('/evidence/"+nonce+"',{method:'POST',body:JSON.stringify({cookie:"+json.dumps(prior)+",storage:previous==='persistent'})});</script>"
  body=html.encode()
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)))
  self.send_header('Cache-Control','no-store')
  self.send_header('Set-Cookie','spx_fixture=persistent; Path=/; Max-Age=86400; HttpOnly; SameSite=Lax')
  self.end_headers();self.wfile.write(body)
 def do_POST(self):
  import re
  nonce=self.path.removeprefix('/evidence/')
  if re.fullmatch('[a-f0-9]{32}',nonce) is None:
   self.send_error(404);return
  size=int(self.headers.get('Content-Length','0'));assert 0<size<2048
  evidence=json.loads(self.rfile.read(size));assert set(evidence)=={'cookie','storage'}
  Path('/home/workspace/.spx-login-evidence-'+nonce+'.json').write_text(json.dumps(evidence))
  self.send_response(204);self.end_headers()
ThreadingHTTPServer(('127.0.0.1',1455),Handler).serve_forever()
'''


def login_fixture(engine, worker, browser, state, start_server=True):
    nonce = secrets.token_hex(16)
    evidence_path = "/home/workspace/.spx-login-evidence-" + nonce + ".json"
    if start_server:
        engine.docker.run("exec", "-d", worker, "python3", "-c", LOGIN_FIXTURE)
    for _ in range(40):
        try:
            execute(engine, browser, "import socket; socket.create_connection(('127.0.0.1',1455),.2).close()")
            break
        except SPXError:
            time.sleep(.1)
    # Each request requires fresh server evidence. Restored tabs or a cached old
    # HTML response must never overwrite a later identity assertion.
    engine.docker.run("exec", *engine.control_env(state), worker, "python3", "/opt/spx/open_browser.py", "http://127.0.0.1:1455/?fixture=" + nonce, timeout=45)
    for _ in range(60):
        raw = execute(engine, worker, "from pathlib import Path; p=Path(" + repr(evidence_path) + "); print(p.read_text() if p.exists() else '')")
        if raw:
            return json.loads(raw)
        time.sleep(.2)
    raise AssertionError("Browser did not execute the controlled login/Profile fixture")


def rejected_sandbox(engine, base):
    from enge_spx.browser_security import PROFILE
    policy = json.loads(PROFILE.read_text())
    # Deliberately deny the namespace variants required by the browser. Preserve
    # every other restriction; never introduce unconfined or container caps.
    policy["syscalls"] = [rule for rule in policy["syscalls"] if not (not rule.get("includes", {}).get("caps") and ("unshare" in rule["names"] or "clone" in rule["names"] and any(arg.get("valueTwo", 0) for arg in rule.get("args", []))))]
    path = base / "sandbox-deny.json"
    path.write_text(json.dumps(policy))
    name = engine.prefix + "-sandbox-rejected"
    obj = engine.ensure_container("browser", engine.image_ids()["browser"], ["--network", "none", "--read-only", "--security-opt", "seccomp=" + str(path), "--memory", "1g", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--tmpfs", "/home/workspace:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700"], name=name)
    engine.deliver_secret(obj["Id"], "browser", {"token": "b" * 64, "proxy": "http://127.0.0.1:9"})
    for _ in range(60):
        if not engine.inspect("browser", name)["State"]["Running"]:
            break
        time.sleep(.5)
    else:
        raise AssertionError("Unsupported sandbox must terminate the browser")
    assert "CHROMIUM_SANDBOX_UNAVAILABLE" in engine.docker.run("logs", obj["Id"])
    assert engine.docker.inspect("container", name)["State"]["ExitCode"] != 0


def security_option_compatibility(engine):
    from enge_spx.browser_security import arguments
    for index, option in enumerate(("no-new-privileges=true", "no-new-privileges:true")):
        name = engine.prefix + "-security-format-" + str(index)
        try:
            obj = engine.ensure_container("browser", engine.image_ids()["work"], ["--network", "none", *arguments(), "--security-opt", option], name=name)
            validate_container(obj)
            value = execute(engine, obj["Id"], "from pathlib import Path; s=Path('/proc/1/status').read_text(); assert 'NoNewPrivs:\\t1' in s; print('NNP_ENABLED')")
            assert value == "NNP_ENABLED", value
        finally:
            obj = engine.inspect("browser", name)
            if obj:
                engine.docker.run("rm", "-f", obj["Id"])


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
            security_option_compatibility(engine)
            passed("real Docker equals/colon no-new-privileges options accepted; PID 1 kernel flag remains enabled")
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
            # Reproduce an upgrade from the old writable/default-seccomp browser
            # without downloading/running an obsolete unsandboxed image. The
            # harmless fixture only writes markers and sleeps, with no network.
            old_browser = engine.ensure_container("browser", engine.image_ids()["work"], ["--network", "none", "--volume", engine.prefix + "-browser-home:/home/workspace", "--volume", engine.prefix + "-downloads:/home/workspace/Downloads"])
            execute(engine, old_browser["Id"], "from pathlib import Path; Path('/home/workspace/.spx-upgrade-profile').write_text('profile'); Path('/home/workspace/Downloads/.spx-upgrade-download').write_text('download')")
            engine.docker.run("stop", "--time", "8", old_browser["Id"])
            try:
                validate_container(engine.inspect("browser"))
            except SPXError:
                pass
            else:
                raise AssertionError("The old browser fixture must fail the new sandbox policy")
            # Exercise a normal 0.8.x bridge through the real check/confirm and
            # detached guard path. Migration calls _stop() inside setup; its
            # stop signal must not cancel the new 190-second monitor below.
            engine.docker.run("network", "rm", engine.internal)
            engine.docker.run("network", "create", "--internal", "--label", engine.owner + "=" + store.instance, engine.internal)
            evidence = engine.check()
            assert engine.docker.inspect("network", engine.internal)["Options"]["com.docker.network.bridge.gateway_mode_ipv4"] == "isolated"
            assert not (store.home / "guard-stop.json").exists()
            passed("ordinary pre-upgrade internal network migrates before review without cancelling the new guard")
            assert engine.inspect("browser") is None, "Stopped pre-sandbox browser was not retired before review"
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
            assert browser["Id"] != old_browser["Id"]
            assert execute(engine, browser["Id"], "from pathlib import Path; print(Path('/home/workspace/.spx-upgrade-profile').read_text()+Path('/home/workspace/Downloads/.spx-upgrade-download').read_text())") == "profiledownload"
            passed("stopped pre-sandbox browser upgrades before confirmation; Profile and downloads survive replacement")
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
            seals = execute(engine, gateway["Id"], '''import os,fcntl
from pathlib import Path
seals=[]
for p in Path('/proc').glob('[0-9]*/fd/*'):
 try:
  if os.readlink(p).startswith('/memfd:spx-config'):
   fd=os.open(p,os.O_RDONLY);seals.append(fcntl.fcntl(fd,fcntl.F_GET_SEALS));os.close(fd)
 except OSError: pass
assert seals and all(v & 15 == 15 for v in seals), 'Gateway config memfd is not sealed'
print('SEALED')''')
            assert seals == "SEALED"
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
            first_identity = login_fixture(engine, worker["Id"], browser["Id"], state)
            assert first_identity == {"cookie": False, "storage": False}, first_identity
            value = execute(engine, browser["Id"], "import urllib.request; print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:1455/?fixture=00000000000000000000000000000000',timeout=5).status)")
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
            restored_identity = login_fixture(engine, resumed["Id"], engine.inspect("browser")["Id"], state)
            assert restored_identity == {"cookie": True, "storage": True}, restored_identity
            passed("real Chromium Cookie and Local Storage survive container stop/recreation; localhost login callback works")
            previous_browser = engine.inspect("browser")["Id"]
            engine.stop_browser()
            assert store.read("runtime.json")["phase"] == "ready"
            assert all(engine.inspect(role)["State"]["Running"] for role in ("gateway", "session"))
            assert engine.docker.inspect("container", resumed["Id"])["State"]["Running"]
            assert not engine.inspect("browser")["State"]["Running"]
            for _ in range(40):
                if not store.read("relay.json", {}):
                    break
                time.sleep(.1)
            else:
                raise AssertionError("Paused browser left its display relay running")
            import subprocess
            for tool in ("claude", "codex"):
                command = engine.tool_command(str(project), [tool, "--version"], interactive=False, browser=False)
                result = subprocess.run(command, capture_output=True, text=True, env=engine.docker.environment(), timeout=30)
                assert result.returncode == 0 and result.stdout.strip(), "CLI startup failed with browser paused"
                assert not engine.inspect("browser")["State"]["Running"]
            passed("stopping only Chromium releases its display relay while both real CLI binaries and the protected network remain usable")
            lock = wait_lock(store)
            try:
                state = engine.ready()
                engine._browser(state)
            finally:
                lock.__exit__(None, None, None)
            reopened = engine.inspect("browser")
            assert reopened["Id"] != previous_browser
            assert login_fixture(engine, resumed["Id"], reopened["Id"], state, start_server=False) == {"cookie": True, "storage": True}
            passed("explicit browser restart validates its sandbox again and preserves real Cookie/Local Storage without restarting CLI")
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
            stopped = engine.shutdown()
            assert stopped["workspace_stopped"] and stopped["background_stopped"]
            assert not list((store.home / "processes").glob("*.json"))
            passed("genuine shutdown verifies all owned containers and detached guard/display services stopped after data relocation")
            rejected_sandbox(engine, base)
            passed("namespace initialization failure terminates the browser without a no-sandbox retry")
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
