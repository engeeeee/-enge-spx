"""Same-host Docker stage measurements against 0.9.0; synthetic data only.

Uses previously verified images from integration_runtime.py. Does not run real AI
service requests, claim WSL2 measurements on Linux, or change global host settings.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import platform
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

BASELINE = "1de64dd76a61ac4fa5f86e28f5bae10a964aced9"


def observer_modules():
    # Use the same current read-only observer for both source versions. Keep it
    # in a separate package so baseline Engine/Store imports stay at the baseline.
    root = Path(__file__).resolve().parent.parent / "src/enge_spx"
    name = "_spx_benchmark_observer"
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from importlib import import_module
    return import_module(name + ".resource_monitor"), import_module(name + ".process_metrics")


TOOL_STARTUP = '''import json,resource,subprocess,sys,time
t=time.perf_counter()
p=subprocess.run([sys.argv[1],'--version'],capture_output=True,text=True,timeout=30)
r=resource.getrusage(resource.RUSAGE_CHILDREN)
assert p.returncode==0
print(json.dumps({'elapsed_ms':(time.perf_counter()-t)*1000,'child_cpu_seconds':r.ru_utime+r.ru_stime,'child_peak_rss_bytes':r.ru_maxrss*1024,'version':p.stdout.strip()[:160]}))
'''

SYNTHETIC = '''import hashlib,threading,time
from pathlib import Path
end=time.monotonic()+10
data=b'x'*(1024*1024)
def work():
 while time.monotonic()<end: hashlib.sha256(data).digest()
threads=[threading.Thread(target=work) for _ in range(2)]
for t in threads:t.start()
Path('/tmp/spx-benchmark-io').write_bytes(b'x'*(8*1024*1024))
for t in threads:t.join()
Path('/tmp/spx-benchmark-done').write_text('done')
'''

BROWSER_FIXTURE = '''from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  data=b"<canvas id='c' width='800' height='600'></canvas><script>const x=c.getContext('2d'),end=Date.now()+15000;fetch('/ready',{method:'POST'});let n=0;function draw(){x.fillStyle='hsl('+(n++%360)+',60%,40%)';x.fillRect(0,0,800,600);if(Date.now()<end)requestAnimationFrame(draw)}draw()</script>"
  self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_POST(self):
  from pathlib import Path
  Path('/tmp/spx-benchmark-page').write_text('ready')
  self.send_response(204);self.end_headers()
ThreadingHTTPServer(('127.0.0.1',1455),Handler).serve_forever()
'''


def worker(args):
    from enge_spx.engine import Engine, GATEWAY_IMAGE, OWNER
    from enge_spx.nodes import parse_nodes
    from enge_spx.state import Store, SPXError, atomic_json
    monitor, metrics = observer_modules()
    supplied = json.loads(args.runtime_report.read_text(encoding="utf-8"))
    report = {"schema": 1, "scope": "Linux Docker; same read-only observer; no real AI tasks, no connected noVNC client, no physical Windows/WSL2 measurement", "mode": args.mode, "stages": {}, "tool_startup": {}, "limitations": ["Only --version startup is measured for Claude/Codex, not service activity.", "CPU/disk and browser canvas loads are synthetic and separately labeled.", "Host totals include observer, test server and other runner processes; container rows include only this instance.", "Docker CLI memory subtracts some cache; limits are not reservations."]}
    with tempfile.TemporaryDirectory(prefix="spx-resource-bench-") as folder:
        base = Path(folder)
        store = Store(base / "data")
        settings = {**store.settings(), "context": args.context}
        if args.mode == "low":
            from enge_spx.resource_limits import preset
            settings["resources"] = preset("low")
        store.write("settings.json", settings)
        store.write("images.json", supplied["images"])
        engine = Engine(store)
        assert engine.recipes == supplied["recipes"], "Benchmark image recipes differ from the verified runtime"
        engine.image_ids()
        observer = metrics.Sampler()
        node_name = engine.prefix + "-benchmark-node"
        def measure(stage, startup_ms=None):
            samples = []
            for _ in range(2):
                samples.append({"containers": monitor.containers(engine), "host": observer.host(), "observer": observer.sample(os.getpid())})
                time.sleep(.3)
            result = {"samples": samples}
            if startup_ms is not None:
                result["startup_ms"] = startup_ms
            result["application_files_bytes"] = sum(path.stat().st_size for path in store.home.rglob("*") if path.is_file())
            report["stages"][stage] = result
            print("MEASURED", args.mode, stage, flush=True)
        def locked(action):
            with store.lock(timeout=45):
                return action()
        def execute(container, code, *tail):
            return engine.docker.run("exec", container, "python3", "-c", code, *tail, timeout=35)
        project = base / "synthetic-project"
        project.mkdir()
        project.chmod(0o777)
        try:
            measure("before_workspace")
            engine.networks()
            password = secrets.token_hex(16)
            directory = base / "server"
            directory.mkdir()
            atomic_json(directory / "config.json", {"dns": {"servers": [{"type": "local", "tag": "local"}]}, "inbounds": [{"type": "shadowsocks", "listen": "0.0.0.0", "listen_port": 8443, "method": "aes-128-gcm", "password": password}], "outbounds": [{"type": "direct", "tag": "direct"}], "route": {"final": "direct", "default_domain_resolver": "local"}})
            engine.docker.run("run", "-d", "--name", node_name, "--user", str(getattr(os, "getuid", lambda: 0)()), "--network", engine.external, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "128m", "--pids-limit", "64", "--label", OWNER + "-benchmark=" + store.instance, "--mount", f"type=bind,source={directory},target=/config,readonly", GATEWAY_IMAGE, "run", "-c", "/config/config.json")
            node_ip = engine.docker.inspect("container", node_name)["NetworkSettings"]["Networks"][engine.external]["IPAddress"]
            auth = base64.urlsafe_b64encode(("aes-128-gcm:" + password).encode()).decode().rstrip("=")
            nodes, _ = parse_nodes(f"ss://{auth}@{node_ip}:8443#Synthetic-benchmark")
            engine.save_nodes(nodes)
            started = time.perf_counter()
            engine.check()
            engine.confirm()
            measure("containers_idle_before_tool", (time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            command = engine.tool_command(str(project), ["true"], interactive=False)
            subprocess.run(command, env=engine.docker.environment(), check=True, timeout=30)
            measure("cli_idle_after_default_launch", (time.perf_counter() - started) * 1000)
            obj, _ = locked(lambda: engine._project(str(project), engine.ready()))
            project_id = obj["Id"]
            for tool in ("claude", "codex"):
                rows = [json.loads(execute(project_id, TOOL_STARTUP, tool)) for _ in range(3)]
                report["tool_startup"][tool] = {"scope": "offline --version child startup only", "samples": rows, "elapsed_median_ms": statistics.median(row["elapsed_ms"] for row in rows), "peak_rss_median_bytes": statistics.median(row["child_peak_rss_bytes"] for row in rows)}
            engine.docker.run("exec", "-d", project_id, "python3", "-c", SYNTHETIC)
            measure("synthetic_cli_cpu_and_disk")
            for _ in range(60):
                if execute(project_id, "from pathlib import Path; print(Path('/tmp/spx-benchmark-done').exists())") == "True":
                    break
                time.sleep(.2)
            else:
                raise AssertionError("Synthetic benchmark workload did not finish")
            engine.docker.run("exec", "-d", project_id, "python3", "-c", BROWSER_FIXTURE)
            for _ in range(30):
                try:
                    execute(project_id, "import socket;socket.create_connection(('127.0.0.1',1455),.2).close()")
                    break
                except SPXError:
                    time.sleep(.1)
            def open_browser():
                state = engine.ready()
                engine._browser(state)
                return state
            started = time.perf_counter()
            state = locked(open_browser)
            browser_start_ms = (time.perf_counter() - started) * 1000
            engine.docker.run("exec", *engine.control_env(state), project_id, "python3", "/opt/spx/open_browser.py", "http://127.0.0.1:1455/", timeout=40)
            for _ in range(50):
                if execute(project_id, "from pathlib import Path;print(Path('/tmp/spx-benchmark-page').exists())") == "True":
                    break
                time.sleep(.1)
            else:
                raise AssertionError("Real Chromium did not execute the synthetic canvas fixture")
            measure("chromium_canvas_active", browser_start_ms)
            browser = engine.inspect("browser")
            report["browser_profile_bytes"] = int(engine.docker.run("exec", browser["Id"], "du", "-sb", "/home/workspace").split()[0])
            report["writable_layers_bytes"] = {row["role"]: json.loads(engine.docker.run("container", "inspect", "--size", "--format", '{"bytes":{{json .SizeRw}}}', row["id"]))["bytes"] for row in monitor.containers(engine)["rows"]}
            if hasattr(engine, "stop_browser"):
                started = time.perf_counter()
                engine.stop_browser()
                measure("browser_stopped_cli_kept", (time.perf_counter() - started) * 1000)
                assert engine.docker.inspect("container", project_id)["State"]["Running"]
            else:
                report["stages"]["browser_stopped_cli_kept"] = {"available": False, "reason": "0.9.0 has no independent browser-stop Engine action"}
            started = time.perf_counter()
            engine.stop()
            for name in ("guard", "forward", "relay"):
                with store.lock(name, timeout=45):
                    pass
            measure("fully_stopped", (time.perf_counter() - started) * 1000)
            assert all(not row["running"] for row in monitor.containers(engine)["rows"])
        finally:
            try:
                engine.stop()
            except Exception:
                pass
            for identifier in engine.managed():
                engine.owned(engine.docker.inspect("container", identifier))
                engine.docker.run("rm", "-f", identifier)
            fixture = engine.docker.inspect("container", node_name)
            if fixture:
                assert fixture["Config"]["Labels"].get(OWNER + "-benchmark") == store.instance
                engine.docker.run("rm", "-f", fixture["Id"])
            for suffix in ("browser-home", "downloads", "tools-home"):
                if engine.docker.inspect("volume", engine.prefix + "-" + suffix):
                    engine.docker.run("volume", "rm", engine.prefix + "-" + suffix)
            for name in (engine.internal, engine.external):
                if engine.docker.inspect("network", name):
                    engine.docker.run("network", "rm", name)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--context", default="default")
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--mode", choices=("normal", "low"), default="normal")
    args = parser.parse_args()
    args.runtime_report = args.runtime_report.resolve()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args)
        return
    root = Path(__file__).resolve().parent.parent
    revision = subprocess.check_output(["git", "rev-parse", args.baseline + "^{commit}"], cwd=root, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="spx-resources-baseline-") as folder:
        baseline = Path(folder)
        archive = baseline / "source.zip"
        with archive.open("wb") as stream:
            subprocess.run(["git", "archive", "--format=zip", revision, "src"], cwd=root, stdout=stream, check=True)
        with zipfile.ZipFile(archive) as source:
            source.extractall(baseline)
        report = {"schema": 1, "platform": platform.platform(), "python": sys.version.split()[0], "baseline_commit": revision, "candidate_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "scope": "Three sequential independent workers on the same Linux Docker runner; shared immutable images; no real AI service account activity, no connected noVNC client; not physical Windows/WSL2.", "results": {}}
        for label, directory, mode in (("baseline_normal", baseline, "normal"), ("candidate_normal", root, "normal"), ("candidate_low", root, "low")):
            output = baseline / (label + ".json")
            env = {**os.environ, "PYTHONPATH": str(directory / "src"), "PYTHONIOENCODING": "utf-8"}
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--mode", mode, "--context", args.context, "--runtime-report", str(args.runtime_report), "--output", str(output)], env=env, cwd=directory, check=True)
            report["results"][label] = json.loads(output.read_text(encoding="utf-8"))
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Resource benchmark evidence saved; no speedup or real-account claim.", flush=True)


if __name__ == "__main__":
    main()
