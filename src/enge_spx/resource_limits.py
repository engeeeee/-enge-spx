"""Versioned budgets; update stopped containers without replacing their data."""
from copy import deepcopy
import math
import re

from .state import SPXError

ROLES = {"gateway": "代理网关", "session": "网络会话", "project": "CLI 项目", "browser": "Chromium"}
MIN_MEMORY = {"gateway": 128, "session": 64, "project": 512, "browser": 512}
NORMAL = {role: {"cpus": 0, "memory_mb": memory} for role, memory in zip(ROLES, (0, 128, 4096, 2048))}
LOW = {role: {"cpus": cpu, "memory_mb": memory} for role, cpu, memory in (("gateway", 1, 256), ("session", .25, 128), ("project", 1, 2048), ("browser", 1, 1024))}


def preset(mode="normal"):
    if mode not in ("normal", "low"):
        raise SPXError("资源模式无效。")
    return {"schema": 1, "mode": mode, "budgets": deepcopy(LOW if mode == "low" else NORMAL), "projects": {}, "auto_browser": mode != "low"}


def validate_budget(value, role):
    if not isinstance(value, dict) or set(value) != {"cpus", "memory_mb"}:
        raise SPXError("资源预算必须包含 CPU 与内存上限。")
    cpu, memory = value["cpus"], value["memory_mb"]
    if isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or cpu < 0 or cpu > 128 or not math.isfinite(cpu) or cpu and cpu < .25 or abs(round(cpu * 100) - cpu * 100) > .000001:
        raise SPXError("CPU 上限应为 0 或 0.25–128 核，最多两位小数；0 表示不限。")
    if isinstance(memory, bool) or not isinstance(memory, int) or memory < 0 or memory > 131072 or memory < MIN_MEMORY[role] and not (role == "gateway" and memory == 0):
        raise SPXError(f"{ROLES[role]}内存上限应为 {MIN_MEMORY[role]}–131072 MiB" + ("，网关也可设为 0（不限）。" if role == "gateway" else "。"))
    return {"cpus": cpu, "memory_mb": memory}


def validate(value=None):
    if value is None:
        return preset()
    if not isinstance(value, dict) or set(value) != {"schema", "mode", "budgets", "projects", "auto_browser"} or value.get("schema") != 1 or isinstance(value.get("schema"), bool):
        raise SPXError("资源设置版本或字段无效，请使用兼容版本恢复；不会自动覆盖。")
    if value["mode"] not in ("normal", "low", "custom") or type(value["auto_browser"]) is not bool:
        raise SPXError("资源模式或浏览器启动选项无效。")
    budgets, projects = value["budgets"], value["projects"]
    if not isinstance(budgets, dict) or set(budgets) != set(ROLES) or not isinstance(projects, dict) or len(projects) > 2000:
        raise SPXError("资源角色或项目预算列表无效。")
    if any(not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{16}", key) for key in projects):
        raise SPXError("项目预算标识无效。")
    return {"schema": 1, "mode": value["mode"], "budgets": {role: validate_budget(budgets[role], role) for role in ROLES}, "projects": {key: validate_budget(item, "project") for key, item in projects.items()}, "auto_browser": value["auto_browser"]}


def budget(config, role, key=None):
    return config["projects"].get(key, config["budgets"][role]) if role == "project" else config["budgets"][role]


def arguments(value, update=False):
    memory = value["memory_mb"] * 1024**2
    result = []
    if memory or update:
        result += ["--memory", str(memory), "--memory-swap", str(memory * 2 if memory else -1)]
    if value["cpus"] or update:
        # CFS -1 restores an unlimited CPU budget without replacing a container.
        result += ["--cpu-period", "100000", "--cpu-quota", str(round(value["cpus"] * 100000) if value["cpus"] else -1)]
    return result


def cpu_limit(host):
    if host.get("NanoCpus", 0):
        return host["NanoCpus"] / 10**9
    quota = host.get("CpuQuota", 0)
    return quota / (host.get("CpuPeriod") or 100000) if quota > 0 else 0


def matches(host, value):
    return host.get("Memory", 0) == value["memory_mb"] * 1024**2 and abs(cpu_limit(host) - value["cpus"]) < .00001


def apply_stopped(engine, obj, value):
    host = obj.get("HostConfig", {})
    if matches(host, value):
        return obj
    if obj["State"]["Running"]:
        raise SPXError("容器资源预算已更改，请先停止环境再重新检查；不会重建项目或强行降低运行中的内存上限。")
    if host.get("NanoCpus", 0):
        raise SPXError("容器存在外部 CPU 配置，无法安全合并预算；容器与数据保持停止且未重建。")
    try:
        engine.docker.run("update", *arguments(value, update=True), obj["Id"])
        updated = engine.owned(engine.docker.inspect("container", obj["Id"]))
        if not matches(updated.get("HostConfig", {}), value):
            raise SPXError("Docker 返回的预算与设置不一致。")
        return updated
    except SPXError as error:
        raise SPXError("容器资源预算未能应用，环境保持停止，原有容器和数据保留。请恢复上次资源设置后重试。") from error
