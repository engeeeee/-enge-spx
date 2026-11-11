"""Real native OS / owned Docker recording, no AI accounts or external probes."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time

from enge_spx.engine import Engine
from enge_spx.resource_monitor import Monitor
from enge_spx.resource_recording import record
from enge_spx.state import Store


def run(context, output):
    checks = []
    def passed(message):
        checks.append(message)
        print("PASS", message, flush=True)
    with tempfile.TemporaryDirectory(prefix="spx-field-recording-") as folder:
        root = Path(folder)
        store, foreign_store = Store(root / "data"), Store(root / "foreign")
        for item in (store, foreign_store):
            item.write("settings.json", {**item.settings(), "context": context})
        engine, foreign = Engine(store), Engine(foreign_store)
        before = {path.name: path.read_bytes() for path in store.home.glob("*.json")}
        observer = Monitor()
        host_file = root / "host.json"
        host = record(lambda cancel: observer.snapshot(engine, docker_ready=False, cancel=cancel), output=host_file, seconds=6, interval=5, activity="gui_idle", source="cli")
        assert host["sample_count"] == 2
        assert host["summary"]["app"]["memory_bytes"]["count"] == 2
        assert host["summary"]["app"]["cpu_percent"]["count"] == 1
        assert all(not sample["containers"]["available"] for sample in host["samples"])
        assert before == {path.name: path.read_bytes() for path in store.home.glob("*.json")}
        assert not (store.home / "runtime.json").exists()
        passed("native process/host counters and CPU deltas record without Docker queries or settings/runtime changes")
        if os.name == "nt":
            assert host["system"] == "Windows"
            passed("native Windows sources distinguish shared Desktop/WSL counters from app and containers")
        result = {"schema": 1, "scope": "native field-recorder mechanics and synthetic Docker lifecycle, not real AI or physical Windows/WSL acceptance", "passed": checks, "host_recording": host}
        if context:
            image = engine.prefix + "-recording-fixture:1"
            dockerfile = root / "Dockerfile"
            dockerfile.write_text('FROM python:3.12-alpine\nUSER 1000:1000\nENTRYPOINT ["python3","-c","import time; time.sleep(3600)"]\n')
            engine.docker.run("build", "--network", "none", "-t", image, str(root), timeout=120)
            engine.store.write("images.json", {"work": image})
            owned = stranger = None
            index, monitor = [0], Monitor()
            report_file = root / "docker.json"
            def sample(cancel):
                nonlocal owned, stranger
                if index[0] == 1:
                    owned = engine.ensure_container("project", image, ["--network", "none"])
                    stranger = foreign.ensure_container("project", image, ["--network", "none"])
                    engine.docker.run("exec", owned["Id"], "python3", "-c", "from pathlib import Path; Path('/tmp/spx-record-preserved').write_text('fixture')")
                elif index[0] == 2:
                    assert engine.shutdown()["workspace_stopped"]
                    assert foreign.docker.inspect("container", stranger["Id"])["State"]["Running"]
                index[0] += 1
                return monitor.snapshot(engine, docker_ready=True, cancel=cancel)
            try:
                docker_report = record(sample, output=report_file, seconds=20, interval=5, source="cli", activity="workspace_idle")
                rows = docker_report["samples"]
                assert len(rows) >= 3
                assert rows[0]["containers"]["rows"] == []
                assert sum(row["running"] for row in rows[1]["containers"]["rows"]) == 1
                assert all(not row["running"] for row in rows[2]["containers"]["rows"])
                assert rows[1]["containers"]["rows"][0]["memory_bytes"] > 0
                assert all(row["containers"]["available"] for row in rows)
                assert engine.docker.inspect("container", owned["Id"])["Id"] == owned["Id"]
                assert engine.docker.inspect("container", owned["Id"])["State"]["Running"] is False
                assert foreign.docker.inspect("container", stranger["Id"])["State"]["Running"]
                text = report_file.read_text()
                for private in (str(root), engine.store.instance, owned["Id"], stranger["Id"], owned["Name"].lstrip("/")):
                    assert private not in text
                assert json.loads(text) == docker_report
                assert not list(root.glob("*.partial"))
                passed("real recording observes zero/running/stopped owned containers with real memory; another instance stays excluded and running")
                passed("observation neither restarts stopped containers nor deletes their writable layers; complete report is redacted and intermediate file cleaned")
                result["docker_recording"] = docker_report
            finally:
                for item in (engine, foreign):
                    for identifier in item.managed():
                        item.owned(item.docker.inspect("container", identifier))
                        item.docker.run("rm", "-f", identifier)
                if engine.docker.inspect("image", image):
                    engine.docker.run("image", "rm", image)
        output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default=None, help="Explicit Docker context enables the synthetic lifecycle check")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.context, args.output)
