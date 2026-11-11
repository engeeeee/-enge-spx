"""Explicit, bounded field measurements using the existing read-only monitor.

No settings, account files, command lines, environment variables or network probes
are collected. Public process/container handles are pseudonymized per recording.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import statistics
import sys
import tempfile
import threading
import time

from . import __version__
from .process_metrics import ACTIONS
from .state import SPXError, atomic_json

ACTIVITIES = {
    "unspecified": "未指定活动", "gui_idle": "界面空闲", "workspace_idle": "工作区空闲",
    "claude": "实际使用 Claude Code", "codex": "实际使用 Codex",
    "browser": "实际使用浏览器", "stopped": "工作区已停止",
}
MAX_SECONDS = 3600
MAX_SAMPLES = 720
MAX_BYTES = 4 * 1024**2
PROCESS_ROLES = {name: action for action, name in ACTIONS.items()}
END_REASONS = {"duration", "user_stop", "app_exit", "storage_change", "interrupted", "size_limit", "sample_limit"}


def settings(seconds=900, interval=10, activity="unspecified"):
    if type(seconds) is not int or not 5 <= seconds <= MAX_SECONDS or type(interval) is not int or not 5 <= interval <= 60 or not isinstance(activity, str) or activity not in ACTIVITIES:
        raise SPXError("记录时长需为 5–3600 秒，间隔为 5–60 秒，并选择预设活动。")
    return {"seconds": seconds, "interval": interval, "activity": activity}


def number(value, maximum=2**60):
    return value if type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value) else None


def _rows(value, maximum):
    return [row for row in value[:maximum] if isinstance(row, dict)] if isinstance(value, list) else []


class Evidence:
    def __init__(self):
        self.salt = secrets.token_bytes(32)

    def alias(self, kind, value):
        return kind + "#" + hmac.new(self.salt, value.encode(), hashlib.sha256).hexdigest()[:12]

    def process(self, row, scope, index):
        pid, created = row.get("pid"), row.get("created")
        valid = type(pid) is int and 0 < pid < 2**32
        identity = str(pid) + ":" + str(created if type(created) is int and 0 <= created <= 2**64 else "unavailable") if valid else "unknown-" + str(index)
        name = row.get("name")
        role = "control" if scope == "app" and index == 0 else PROCESS_ROLES.get(name, "service") if scope == "app" and isinstance(name, str) else "service" if scope == "app" else scope
        return {"handle": self.alias("process", identity), "role": role, "available": row.get("available") is True,
                "cpu_percent": number(row.get("cpu_percent"), 1000000), "memory_bytes": number(row.get("memory_bytes")), "private_bytes": number(row.get("private_bytes"))}

    def sample(self, raw, elapsed):
        raw = raw if isinstance(raw, dict) else {}
        host = raw.get("host") if isinstance(raw.get("host"), dict) else {}
        supplied = raw.get("containers") if isinstance(raw.get("containers"), dict) else {}
        rows = []
        for index, row in enumerate(_rows(supplied.get("rows"), 256)):
            identifier = row.get("id")
            identity = identifier if isinstance(identifier, str) and re.fullmatch(r"[a-f0-9]{12,64}", identifier) else "unknown-" + str(index)
            if row.get("role") not in ("gateway", "session", "project", "browser"):
                continue
            rows.append({"handle": self.alias("container", identity), "role": row["role"], "running": row.get("running") is True,
                         "available": row.get("sample_available") is True, "oom": row.get("oom") is True,
                         **{key: number(row.get(key), 1000000 if key in ("cpu_percent", "cpu_limit", "pids") else 2**60) for key in ("cpu_percent", "memory_bytes", "memory_limit", "cpu_limit", "read_bytes", "write_bytes", "pids")}})
        desktop, wsl = [], []
        for row in _rows(raw.get("desktop"), 128):
            group = wsl if row.get("scope") == "wsl" else desktop
            group.append(self.process(row, "wsl" if group is wsl else "desktop", len(group)))
        return {"elapsed_seconds": round(elapsed, 3), "host": {"available": host.get("available") is True, **{key: number(host.get(key), 100 if key == "cpu_percent" else 2**60) for key in ("cpu_percent", "memory_used", "memory_total")}},
                "app": [self.process(row, "app", index) for index, row in enumerate(_rows(raw.get("app"), 128))],
                "background_unavailable": number(raw.get("background_unavailable"), 1000000), "docker_desktop": desktop, "wsl": wsl,
                "containers": {"available": supplied.get("available") is True, "truncated": supplied.get("truncated") is True, "rows": rows}}


def _total(rows, field):
    if any(not row.get("available") or row.get(field) is None for row in rows):
        return None
    return sum(row[field] for row in rows)


def summary(samples):
    """Summarize discrete observations, without claiming unobserved peaks."""
    groups = {group: {"available_samples": 0, "cpu_percent": [], "memory_bytes": []} for group in ("host", "app", "docker_desktop", "wsl", "containers")}
    for sample in samples:
        for group, values in groups.items():
            if group == "host":
                available = sample["host"]["available"]
                cpu, memory = sample["host"]["cpu_percent"], sample["host"]["memory_used"]
            else:
                container = group == "containers"
                rows = [row for row in sample["containers"]["rows"] if row["running"]] if container else sample[group]
                available = sample["containers"]["available"] and not sample["containers"]["truncated"] if container else bool(rows)
                if group == "app" and sample["background_unavailable"] not in (None, 0):
                    available = False
                cpu, memory = (_total(rows, field) for field in ("cpu_percent", "memory_bytes"))
            if available:
                values["available_samples"] += 1
                for field, value in (("cpu_percent", cpu), ("memory_bytes", memory)):
                    if value is not None:
                        values[field].append(value)
    return {group: {"available_samples": values["available_samples"], **{field: {"count": len(rows), "min": min(rows), "median": statistics.median(rows), "max_sampled": max(rows)} if rows else {"count": 0} for field, rows in values.items() if field != "available_samples"}} for group, values in groups.items()}


class RecordingError(SPXError):
    def __init__(self, report):
        super().__init__("记录文件无法保存，请选择可写目录后重新导出。已经写入的 .partial 中间文件会保留；安全监测不受影响。")
        self.report = report


def record(provider, *, output, seconds=900, interval=10, activity="unspecified", source="cli", cancel=None,
           stop_reason=lambda: "user_stop", on_sample=lambda raw, count, elapsed: None,
           clock=time.monotonic, wait=None):
    config = settings(seconds, interval, activity)
    if source not in ("cli", "gui"):
        raise SPXError("记录来源无效。")
    cancel = cancel or threading.Event()
    wait = wait or cancel.wait
    output = Path(output)
    evidence, samples = Evidence(), []
    started = clock()
    report = {"schema": 1, "kind": "resource_recording", "version": __version__, "source": source,
              "system": "Windows" if sys.platform == "win32" else "Linux" if sys.platform.startswith("linux") else "other",
              "recorded_utc": datetime.now(timezone.utc).isoformat(), "requested": config,
              "activity_evidence": "user-selected label; no AI command, prompt or account inspection",
              "notes": ["Measurements include observer overhead; CLI control counters describe this recorder, not an unregistered GUI.",
                        "Process/container CPU uses one-core percent; host CPU uses whole-host percent. First process CPU requires a second sample.",
                        "Working sets may share pages. Docker memory excludes some cache. WSL includes other distributions/cache; groups must not be added together.",
                        "Maximum sampled values are discrete observations, not guaranteed peaks. Docker I/O counters are cumulative, not bandwidth.",
                        "Sampling is sequential, with the requested gap after each query. Missing counters are not zero usage.",
                        "No Docker startup, lease renewal, network probe, resource-limit change or automatic upload is performed."], "samples": samples}
    reason, estimated = "duration", 0
    stream, temporary, fd = None, None, -1
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="." + output.name + ".", suffix=".partial", dir=output.parent)
        temporary = Path(name)
        stream = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        stream.write(json.dumps({"type": "header", "report": report}, allow_nan=False) + "\n")
        stream.flush()
        while clock() - started < seconds:
            if cancel.is_set():
                reason = stop_reason()
                reason = reason if reason in END_REASONS else "user_stop"
                break
            if len(samples) >= MAX_SAMPLES:
                reason = "sample_limit"
                break
            try:
                raw = provider(cancel)
            except KeyboardInterrupt:
                reason = "interrupted"
                break
            except Exception:
                raw = None  # Never expose exception text, paths or credentials.
            if cancel.is_set():
                reason = stop_reason()
                reason = reason if reason in END_REASONS else "user_stop"
                break
            elapsed = clock() - started
            sample = evidence.sample(raw, elapsed)
            encoded = json.dumps(sample, indent=2, allow_nan=False)
            cost = len(encoded.encode()) + 4 * (encoded.count("\n") + 1) + 2
            if estimated + cost > MAX_BYTES - min(65536, MAX_BYTES // 3):
                reason = "size_limit"
                break
            samples.append(sample)
            estimated += cost
            stream.write(json.dumps({"type": "sample", "sample": sample}, allow_nan=False) + "\n")
            stream.flush()
            on_sample(raw, len(samples), elapsed)
            wait(max(0, min(interval, seconds - (clock() - started))))
    except KeyboardInterrupt:
        reason = "interrupted"
    except OSError:
        reason = "write_error"
    finally:
        if stream:
            try:
                stream.close()
            except OSError:
                reason = "write_error"
        elif fd >= 0:
            os.close(fd)
    report.update(end_reason=reason, elapsed_seconds=round(clock() - started, 3), sample_count=len(samples), summary=summary(samples))
    report["coverage"] = "unavailable" if not samples else "partial" if any(not row["host"]["available"] or row["host"]["memory_used"] is None or not row["app"] or row["background_unavailable"] not in (None, 0) or any(not item["available"] or item["memory_bytes"] is None for item in [*row["app"], *row["docker_desktop"], *row["wsl"]]) or not row["containers"]["available"] or row["containers"]["truncated"] or any(item["running"] and (not item["available"] or item["memory_bytes"] is None) for item in row["containers"]["rows"]) for row in samples) else "available"
    if reason == "write_error":
        raise RecordingError(report)
    try:
        if len(json.dumps(report, indent=2, allow_nan=False).encode()) > MAX_BYTES:
            raise OSError("Recording size limit")
        atomic_json(output, report)
    except OSError as error:
        raise RecordingError(report) from error
    if temporary:
        try:
            temporary.unlink()
        except OSError:
            pass
    return report
