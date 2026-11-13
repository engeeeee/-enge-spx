"""Bounded, thread-local exit evidence; no raw errors or command output."""
from contextlib import contextmanager
from contextvars import ContextVar
from collections import deque
import re
import time

from . import __version__

_checks = ContextVar("spx_exit_checks", default=None)
_token = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


@contextmanager
def capture_checks():
    rows = deque(maxlen=64)
    token = _checks.set(rows)
    try:
        yield rows
    finally:
        _checks.reset(token)


def add_check(component, stage, result, error=None):
    rows = _checks.get()
    if rows is None or any(not isinstance(value, str) or not _token.fullmatch(value) for value in (component, stage, result)):
        return
    row = {"component": component, "stage": stage, "result": result}
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    if type(code) is int:
        row["os_code"] = code
    rows.append(row)


def failure_report(stage, checks, error, workspace_stopped=False):
    return {"schema": 1, "app": "ENGE SPX", "version": __version__,
            "source": "gui_exit", "time": time.time(),
            "stage": stage if stage in ("workspace", "desktop") else "unknown",
            "error_type": type(error).__name__[:64],
            "workspace_stop_verified": workspace_stopped is True,
            "desktop_stop_verified": False, "checks": list(checks)[-64:],
            "checks_may_be_truncated": len(checks) >= 64}
