"""Same-runner P0 overhead measurements; synthetic data, no production accounts.

Windows: python tools/benchmark_p0.py --kind host --output host.json
Linux Docker: python tools/benchmark_p0.py --kind docker --context default --output docker.json
Baseline must already exist in local git history (CI checks out with fetch-depth: 0).
"""
import argparse
import ctypes
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

BASELINE = "c08beb1f3224150d95dbc1c5fb05e1283ff9c5ff"


def median_ms(action, count):
    samples = []
    for _ in range(count):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 3)


def resident_bytes():
    if os.name == "nt":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
        kernel = ctypes.WinDLL("kernel32", winmode=0x00000800)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", winmode=0x00000800)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("Process memory measurement failed")
        return counters.WorkingSetSize
    fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    return int(fields["VmRSS"].split()[0]) * 1024


def host_measure(store):
    from enge_spx.engine import Engine
    from enge_spx.nodes import parse_nodes
    nodes, _ = parse_nodes("\n".join(f"socks5://fixture:synthetic-{index}@192.0.2.1:{10000+index}#Benchmark-{index}" for index in range(20)))
    start = time.perf_counter()
    if hasattr(store, "migrate_credentials"):
        store.migrate_credentials()
    migration_ms = (time.perf_counter() - start) * 1000
    store.write("nodes.json", nodes)
    store.write("settings.json", {**store.settings(), "selected": nodes[0]["id"]})
    output = {"mode": "dpapi-current-user" if getattr(getattr(store, "credentials", None), "enabled", False) else "private-files", "initial_migration_ms": round(migration_ms, 3), "write_20_nodes_ms": median_ms(lambda: store.write("nodes.json", nodes), 15), "read_20_nodes_ms": median_ms(lambda: store.read("nodes.json"), 100), "engine_construction_ms": median_ms(lambda: Engine(store), 15)}
    # No Docker/WSL is started. CPU is the measured process, as % of one core.
    start, cpu = time.perf_counter(), time.process_time()
    time.sleep(1)
    output["idle_python_cpu_percent_one_core"] = round((time.process_time()-cpu)/(time.perf_counter()-start)*100, 4)
    start = time.perf_counter()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from enge_spx.ui.controller import Controller
    from enge_spx.ui.window import Window
    app = QApplication([])
    window = Window(Controller(store))
    window.show()
    app.processEvents()
    output["gui_import_construct_first_paint_ms"] = round((time.perf_counter()-start)*1000, 3)
    start, cpu = time.perf_counter(), time.process_time()
    QTimer.singleShot(5000, app.quit)
    app.exec()
    output["gui_idle_seconds"] = round(time.perf_counter()-start, 3)
    output["gui_idle_cpu_percent_one_core"] = round((time.process_time()-cpu)/output["gui_idle_seconds"]*100, 4)
    output["gui_working_set_bytes"] = resident_bytes()
    output["persistent_bytes"] = sum(p.stat().st_size for p in store.home.rglob("*") if p.is_file())
    window.close()
    return output


def docker_measure(store, context):
    from enge_spx.engine import Engine
    store.write("settings.json", {**store.settings(), "context": context})
    engine = Engine(store)
    def cleanup_networks():
        for network in (engine.internal, engine.external):
            obj = engine.docker.inspect("network", network)
            if obj:
                engine.owned(obj)
                engine.docker.run("network", "rm", network)
    with ExitStack() as cleanup:
        cleanup.callback(cleanup_networks)
        engine.install()
        image = engine.image_ids()["browser"]
        secure = hasattr(engine, "deliver_secret")
        samples = []
        for index in range(3):
            name = engine.prefix + "-browser"
            volume = engine.prefix + "-benchmark-" + str(index)
            try:
                args = ["--network", "none", "--shm-size", "512m", "--memory", "2g", "--volume", volume + ":/home/workspace", "--env", "HTTP_PROXY=http://127.0.0.1:9"]
                if secure:
                    from enge_spx.browser_security import arguments, validate_container, validate_status
                    args += arguments()
                else:
                    # Synthetic baseline capability only; never used by current runtime.
                    args += ["--env", "SPX_BROWSER_TOKEN=" + "b" * 64]
                start = time.perf_counter()
                obj = engine.ensure_container("browser", image, args)
                if secure:
                    validate_container(obj)
                    engine.deliver_secret(obj["Id"], "browser", {"token": "b" * 64, "proxy": "http://127.0.0.1:9"})
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    result = subprocess.run(engine.docker.command("exec", obj["Id"], "python3", "-c", "import socket; socket.create_connection(('127.0.0.1',6081),.2).close()"), capture_output=True, env=engine.docker.environment())
                    if result.returncode == 0:
                        break
                    if not engine.inspect("browser")["State"]["Running"]:
                        raise RuntimeError("Benchmark browser exited: " + engine.docker.run("logs", obj["Id"]))
                    time.sleep(.1)
                else:
                    raise RuntimeError("Benchmark browser did not become ready")
                sample = {"startup_ms": round((time.perf_counter()-start)*1000, 3)}
                if secure:
                    sample["sandbox"] = validate_status(json.loads(engine.docker.run("exec", obj["Id"], "cat", "/tmp/spx-sandbox-status.json")))
                time.sleep(5)
                sample["docker_stats"] = [json.loads(engine.docker.run("stats", "--no-stream", "--format", "{{json .}}", obj["Id"])) for _ in range(3)]
                sample["processes"] = max(0, len(engine.docker.run("top", obj["Id"], "-eo", "pid").splitlines())-1)
                sample["profile_bytes"] = int(engine.docker.run("exec", obj["Id"], "du", "-sb", "/home/workspace").split()[0])
                info = json.loads(engine.docker.run("container", "inspect", "--size", obj["Id"]))[0]
                sample["writable_layer_bytes"] = info["SizeRw"]
                start = time.perf_counter()
                engine.docker.run("stop", "--time", "8", obj["Id"])
                sample["stop_ms"] = round((time.perf_counter()-start)*1000, 3)
                sample["running_after_stop"] = engine.inspect("browser")["State"]["Running"]
                samples.append(sample)
            finally:
                engine.docker.run("rm", "-f", name)
                engine.docker.run("volume", "rm", volume)
        return {"scope": "browser container; network none; default local startup document; no noVNC client", "sandbox": secure, "samples": samples, "startup_median_ms": round(statistics.median(s["startup_ms"] for s in samples), 3), "docker": engine.doctor()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("host", "docker"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", default="default")
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        from enge_spx.state import Store
        with tempfile.TemporaryDirectory(prefix="spx-p0-bench-") as folder:
            store = Store(Path(folder) / "private")
            value = host_measure(store) if args.kind == "host" else docker_measure(store, args.context)
            args.output.write_text(json.dumps(value, indent=2))
        return
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="spx-baseline-source-") as folder:
        baseline = Path(folder)
        revision = subprocess.check_output(["git", "rev-parse", "--verify", args.baseline + "^{commit}"], cwd=root, text=True).strip()
        data = subprocess.check_output(["git", "archive", "--format=zip", revision, "src"], cwd=root)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(baseline)
        report = {"schema": 1, "platform": platform.platform(), "python": sys.version.split()[0], "baseline_commit": revision, "candidate_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "kind": args.kind, "results": {}}
        for label, source in (("baseline", baseline), ("candidate", root)):
            output = baseline / (label + ".json")
            env = {**os.environ, "PYTHONPATH": str(source / "src"), "PYTHONIOENCODING": "utf-8"}
            if os.name != "nt":
                env["QT_QPA_PLATFORM"] = "offscreen"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--kind", args.kind, "--context", args.context, "--output", str(output)], env=env, cwd=source, check=True)
            report["results"][label] = json.loads(output.read_text())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
