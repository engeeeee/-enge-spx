"""Real Linux cgroup budgets and data reuse, with network-none synthetic fixtures."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time

from enge_spx.engine import Engine
from enge_spx.resource_limits import preset
from enge_spx.resource_monitor import containers
from enge_spx.state import SPXError, Store

IDLE = "import signal,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); time.sleep(3600)"
COUNTERS = '''import json
from pathlib import Path
p=Path('/sys/fs/cgroup')
if (p/'memory.max').exists():
 print(json.dumps({'version':2,'memory':(p/'memory.max').read_text().strip(),'cpu':(p/'cpu.max').read_text().strip()}))
else:
 print(json.dumps({'version':1,'memory':(p/'memory/memory.limit_in_bytes').read_text().strip(),'quota':(p/'cpu/cpu.cfs_quota_us').read_text().strip(),'period':(p/'cpu/cpu.cfs_period_us').read_text().strip()}))
'''


def run(context, output):
    records, measured = [], {}
    def passed(message):
        records.append(message)
        print("PASS", message, flush=True)
    with tempfile.TemporaryDirectory(prefix="spx-resource-test-") as folder:
        root = Path(folder)
        store, foreign_store = Store(root / "data"), Store(root / "other")
        for item in (store, foreign_store):
            item.write("settings.json", {**item.settings(), "context": context})
        engine, foreign = Engine(store), Engine(foreign_store)
        try:
            image = engine.docker.inspect("image", "python:3.12-alpine")
            if not image:
                engine.docker.run("pull", "python:3.12-alpine", timeout=300)
                image = engine.docker.inspect("image", "python:3.12-alpine")
            image_id = image["Id"]
            # Fixture image records make stop() exercise its real owned-container
            # path. These images are not installed as application runtime images.
            store.write("images.json", {role: image_id for role in ("gateway", "work", "browser")})
            paths = [root / "first", root / "second"]
            for path in paths:
                path.mkdir()
            keys = [store.project(str(path))[1] for path in paths]
            names = [engine.prefix + "-project-" + key for key in keys]
            def ensure(index):
                return engine.ensure_container("project", image_id, ["--network", "none", "--user", "1000:1000"], ["python", "-u", "-c", IDLE], name=names[index], resource_key=keys[index])
            def gateway():
                return engine.ensure_container("gateway", image_id, ["--network", "none", "--user", "1000:1000"], ["python", "-u", "-c", IDLE])
            original_gateway = gateway()
            originals = [ensure(index) for index in range(2)]
            outsider = foreign.ensure_container("project", image_id, ["--network", "none", "--user", "1000:1000"], ["python", "-u", "-c", IDLE])
            for obj in originals:
                engine.docker.run("exec", obj["Id"], "python", "-c", "from pathlib import Path; Path('/tmp/spx-budget-layer').write_text('persistent')")
            config = preset("low")
            config["budgets"]["project"] = {"cpus": .5, "memory_mb": 512}
            config["projects"][keys[1]] = {"cpus": .75, "memory_mb": 768}
            store.write("runtime.json", {"phase": "ready"})
            engine.save_resources(config)
            assert all(not engine.docker.inspect("container", obj["Id"])["State"]["Running"] for obj in originals)
            assert foreign.docker.inspect("container", outsider["Id"])["State"]["Running"]
            passed("saving changed budgets stops only owned containers and leaves unrelated workloads running")
            updated = [ensure(index) for index in range(2)]
            limited_gateway = gateway()
            assert limited_gateway["Id"] == original_gateway["Id"]
            assert limited_gateway["HostConfig"]["Memory"] == 256 * 1024**2
            assert [obj["Id"] for obj in updated] == [obj["Id"] for obj in originals]
            for index, obj in enumerate(updated):
                assert engine.docker.run("exec", obj["Id"], "cat", "/tmp/spx-budget-layer") == "persistent"
                assert obj["HostConfig"]["Privileged"] is False
                assert obj["HostConfig"]["CapDrop"] == ["ALL"]
                assert obj["HostConfig"]["NetworkMode"] == "none"
                assert not obj["HostConfig"]["PortBindings"]
                counters = json.loads(engine.docker.run("exec", obj["Id"], "python", "-c", COUNTERS))
                expected = (512, 768)[index] * 1024**2
                quota = (50000, 75000)[index]
                assert int(counters["memory"]) == expected, counters
                if counters["version"] == 2:
                    assert counters["cpu"] == f"{quota} 100000", counters
                else:
                    assert int(counters["quota"]) == quota and int(counters["period"]) == 100000, counters
                measured[f"project_{index}"] = counters
            passed("real cgroups enforce distinct project CPU/memory budgets; container IDs and writable files survive")
            sample = containers(engine)
            assert len(sample["rows"]) == 3 and all(row["sample_available"] for row in sample["rows"])
            assert all(row["memory_bytes"] > 0 for row in sample["rows"])
            assert all(row["id"] != outsider["Id"] for row in sample["rows"])
            measured["sample"] = sample
            passed("bounded scoped Docker stats reports actual memory, CPU, I/O and limits without sampling foreign containers")
            invalid = deepcopy(config)
            invalid["budgets"]["project"]["memory_mb"] = 1
            try:
                engine.save_resources(invalid)
            except SPXError:
                pass
            else:
                raise AssertionError("Unsafe budget accepted")
            assert all(engine.docker.inspect("container", obj["Id"])["State"]["Running"] for obj in updated)
            passed("invalid memory budgets reject before stopping any running work")
            changed = deepcopy(config)
            changed["budgets"]["project"]["memory_mb"] = 1024
            engine.save_resources(changed)
            execute = engine.docker.run
            def denied(*args, **kwargs):
                if args[0] == "update":
                    raise SPXError("Synthetic Docker resource denial")
                return execute(*args, **kwargs)
            engine.docker.run = denied
            try:
                try:
                    ensure(0)
                except SPXError:
                    pass
                else:
                    raise AssertionError("A failed budget update started the container")
                assert not engine.docker.inspect("container", originals[0]["Id"])["State"]["Running"]
            finally:
                engine.docker.run = execute
            engine.restore_resources()
            restored = ensure(0)
            assert restored["Id"] == originals[0]["Id"]
            assert engine.docker.run("exec", restored["Id"], "cat", "/tmp/spx-budget-layer") == "persistent"
            passed("resource update denial keeps the container stopped; restoring last settings reuses its data")
            engine.save_resources(preset())
            normal_gateway, normal_project = gateway(), ensure(0)
            assert normal_gateway["Id"] != original_gateway["Id"]
            assert normal_gateway["HostConfig"]["Memory"] == 0
            assert normal_project["Id"] == originals[0]["Id"]
            assert normal_project["HostConfig"]["Memory"] == 4 * 1024**3
            assert normal_project["HostConfig"]["CpuQuota"] == -1
            assert engine.docker.run("exec", normal_project["Id"], "cat", "/tmp/spx-budget-layer") == "persistent"
            measured["normal_restored"] = {"gateway_memory": 0, "project_memory": normal_project["HostConfig"]["Memory"], "project_quota": normal_project["HostConfig"]["CpuQuota"]}
            passed("normal mode removes CPU quota and restores old memory budgets; only the data-free gateway is replaced")
            result = engine.shutdown()
            assert result["workspace_stopped"] and result["background_stopped"]
            sample = containers(engine)
            assert all(not row["running"] and not row["sample_available"] for row in sample["rows"])
            assert foreign.docker.inspect("container", outsider["Id"])["State"]["Running"]
            passed("complete workspace stop leaves no running owned fixture or stats stream and preserves unrelated work")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"schema": 1, "scope": "network-none Linux cgroup fixtures; not real AI accounts or WSL2", "passed": records, "evidence": measured, "time": time.time()}, indent=2) + "\n", encoding="utf-8")
        finally:
            for owner in (engine, foreign):
                for identifier in owner.managed():
                    owner.owned(owner.docker.inspect("container", identifier))
                    owner.docker.run("rm", "-f", identifier)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="default")
    parser.add_argument("--output", type=Path, default=Path("resource-results.json"))
    args = parser.parse_args()
    run(args.context, args.output)
