"""On-demand, bounded resource evidence. Never starts Docker or renews leases."""
import itertools
import json
import math
import os
import re
import time
from types import SimpleNamespace

from . import process_metrics
from .resource_limits import ROLES, cpu_limit
from .state import SPXError
from .docker_env import require_local_context

MAX_CONTAINERS = 256


def sampling_target(store, context=None):
    """Build a telemetry-only target without decrypting nodes/settings/runtime."""
    from .engine import Docker, OWNER, ROLE
    from .brand import LEGACY_LABEL_ROOT
    if context is None:
        try:
            saved = store.read("controller-context.json", {})
            if isinstance(saved, dict) and saved.get("instance") == store.instance:
                context = saved.get("context")
        except (SPXError, OSError):
            pass
    verified = isinstance(context, str) and bool(context) and len(context) <= 256
    return SimpleNamespace(store=store, docker=Docker(context if verified else "desktop-linux"),
                           owner=LEGACY_LABEL_ROOT + ".instance" if store.legacy else OWNER,
                           role=LEGACY_LABEL_ROOT + ".role" if store.legacy else ROLE,
                           ready=verified)


def byte_count(value):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*", value)
    if not match:
        raise ValueError("Invalid Docker byte count")
    units = {"B": 1, **{unit: 1000**index for index, unit in enumerate(("kB", "MB", "GB", "TB"), 1)}, **{unit: 1024**index for index, unit in enumerate(("KiB", "MiB", "GiB", "TiB"), 1)}}
    return round(float(match[1]) * units[match[2]])


def _percent(value):
    number = float(value.removesuffix("%"))
    if not math.isfinite(number) or number < 0:
        raise ValueError("Invalid CPU counter")
    return number


def containers(engine, cancel=None):
    def checkpoint():
        if cancel is not None and cancel.is_set():
            raise SPXError("资源采样已取消。")
    checkpoint()
    require_local_context(engine.docker, timeout=6)
    checkpoint()
    # Do not read environment variables, mounts, command lines or credentials.
    ids = engine.docker.run("ps", "-aq", "--filter", "label=" + engine.owner + "=" + engine.store.instance, timeout=6).splitlines()
    if not ids:
        return {"available": True, "rows": [], "truncated": False}
    if any(not re.fullmatch(r"[a-f0-9]{12,64}", identifier) for identifier in ids):
        raise SPXError("容器标识无效，未查询其它资源。")
    selected = ids[:MAX_CONTAINERS]
    checkpoint()
    template = '{"id":{{json .Id}},"name":{{json .Name}},"owner":{{json (index .Config.Labels "' + engine.owner + '")}},"role":{{json (index .Config.Labels "' + engine.role + '")}},"running":{{json .State.Running}},"oom":{{json .State.OOMKilled}},"memory_limit":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}},"period":{{json .HostConfig.CpuPeriod}},"quota":{{json .HostConfig.CpuQuota}}}'
    raw = engine.docker.run("container", "inspect", "--format", template, *selected, timeout=8)
    if len(raw) > 2 * 1024**2:
        raise SPXError("容器资源信息过大。")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) != len(selected) or any(row.get("owner") != engine.store.instance or not any(row.get("id", "").startswith(identifier) for identifier in selected) for row in rows):
        raise SPXError("资源归属不一致，未采样其它容器。")
    rows = [row for row in rows if row.get("role") in ROLES]
    running = [row["id"] for row in rows if row["running"]]
    statistics = {}
    if running:
        checkpoint()
        # An empty ID list would mean all containers. Never issue that command.
        raw = engine.docker.run("stats", "--no-stream", "--no-trunc", "--format", "{{json .}}", *running, timeout=8)
        if len(raw) > 2 * 1024**2:
            raise SPXError("容器采样信息过大。")
        for line in raw.splitlines():
            value = json.loads(line)
            identifier = value.get("ID", "")
            candidates = [item for item in running if identifier and item.startswith(identifier)]
            if len(candidates) != 1:
                raise SPXError("采样容器与本实例资源不一致。")
            used, limit = value["MemUsage"].split("/")
            read, written = value["BlockIO"].split("/")
            statistics[candidates[0]] = {"cpu_percent": _percent(value["CPUPerc"]), "memory_bytes": byte_count(used), "reported_memory_limit": byte_count(limit), "read_bytes": byte_count(read), "write_bytes": byte_count(written), "pids": int(value["PIDs"])}
    result = []
    for row in rows:
        counters = statistics.get(row["id"], {})
        result.append({"id": row["id"], "name": row["name"].removeprefix("/"), "role": row["role"], "running": row["running"], "oom": row["oom"], "cpu_limit": cpu_limit({"NanoCpus": row["nano_cpus"], "CpuPeriod": row["period"], "CpuQuota": row["quota"]}), "memory_limit": row["memory_limit"], "sample_available": row["id"] in statistics, **counters})
    return {"available": True, "rows": result, "truncated": len(ids) > len(selected)}


class Monitor:
    def __init__(self):
        self.sampler = process_metrics.Sampler()

    def snapshot(self, engine, docker_ready=False, cancel=None):
        app = [{"name": "ENGE SPX 控制进程", "scope": "app", **self.sampler.sample(os.getpid())}]
        registry = engine.store.home / "processes"
        unavailable = 0
        for path in itertools.islice(registry.glob("*.json"), 128):
            if not re.fullmatch(r"(guard|forward|relay)-[1-9][0-9]*\.json", path.name):
                continue
            try:
                record = engine.store.read("processes/" + path.name, {})
                action = record.get("action")
                if record.get("schema") != 1 or action not in process_metrics.ACTIONS or path.name != f"{action}-{record.get('pid')}.json":
                    continue
                value = self.sampler.sample(record["pid"])
                if value.get("created") != record.get("created") or not value.get("available"):
                    unavailable += 1
                    continue  # A reused PID is not one of our background services.
                app.append({"name": process_metrics.ACTIONS[action], "scope": "app", **value})
            except (OSError, SPXError, ValueError, KeyError, TypeError):
                unavailable += 1
        desktop = [{**item, **self.sampler.sample(item["pid"])} for item in process_metrics.desktop_processes()]
        evidence = {"schema": 1, "sampled": time.time(), "cpu_units": "one-core percent for processes/containers; whole-host percent for host", "host": self.sampler.host(), "app": app, "background_unavailable": unavailable, "desktop": desktop, "windows": os.name == "nt", "containers": {"available": False, "reason": "Docker 尚未就绪；资源面板不会启动 Docker。", "rows": []}}
        if docker_ready:
            try:
                evidence["containers"] = containers(engine, cancel)
            except (OSError, SPXError, ValueError, KeyError, TypeError, AttributeError):
                evidence["containers"] = {"available": False, "reason": "容器采样暂不可用；Docker 未连接、资源正在变化或权限不足。", "rows": []}
        retained = {item["pid"] for item in [*app, *desktop]}
        self.sampler.previous = {pid: value for pid, value in self.sampler.previous.items() if pid in retained}
        return evidence
