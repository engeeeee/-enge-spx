"""Explicit Windows Desktop shutdown, separate from owner-scoped Engine.stop."""
import json
import logging
import os
import subprocess
import time

from .docker_env import environment, require_local_context
from .state import SPXError
from .exit_diagnostics import add_check
from .local_process import run as run_bounded

PREFERENCES = "exit-preferences.json"
log = logging.getLogger("enge_spx.gui")


def _record(stage, result, error=None):
    log.info("desktop-exit-check stage=%s result=%s error_type=%s", stage, result,
             type(error).__name__ if error else "none")
    add_check("desktop", stage, result, error)


def load_preference(store):
    raw = store.read(PREFERENCES, None)
    if raw is None:
        return False
    if not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw.get("schema") != 1 or type(raw.get("close_docker_desktop")) is not bool:
        raise SPXError("退出偏好无效或版本不支持；联合关闭未启用，请保留原文件并检查设置。")
    return raw["close_docker_desktop"]


def save_preference(store, enabled):
    if type(enabled) is not bool:
        raise SPXError("请选择是否在真正退出时关闭 Docker Desktop。")
    try:
        with store.lock("exit-preferences", timeout=3):
            # A future schema must not be destroyed by an older application.
            raw = store.read(PREFERENCES, None)
            if isinstance(raw, dict) and raw.get("schema", 1) != 1:
                raise SPXError("退出偏好版本不支持，请使用对应版本处理；未覆盖原文件。")
            store.write(PREFERENCES, {"schema": 1, "close_docker_desktop": enabled})
    except SPXError:
        raise
    except OSError:
        raise SPXError("无法保存退出偏好，请检查数据目录权限；原设置保持不变。") from None
    return enabled


class DesktopShutdownError(SPXError):
    def __init__(self, code):
        messages = {
            "missing": "未找到 Docker 命令行，无法正常关闭 Docker Desktop。",
            "status": "无法读取 Docker Desktop 管理状态。当前版本可能不支持管理接口，或权限不足。",
            "stop": "Docker Desktop 未完成正常关闭，请检查其窗口提示并重试。",
            "timeout": "等待 Docker Desktop 正常关闭超时；未强制结束进程。",
        }
        super().__init__(messages[code])
        self.code = code


def _command(docker, *args, timeout):
    if not docker.executable:
        raise DesktopShutdownError("missing")
    if timeout <= 0:
        raise DesktopShutdownError("timeout")
    try:
        return run_bounded([docker.executable, "desktop", *args], timeout=timeout,
                           env=environment(docker.executable))
    except subprocess.TimeoutExpired:
        raise DesktopShutdownError("timeout") from None
    except OSError:
        raise DesktopShutdownError("status" if args[0] == "status" else "stop") from None


def _status(docker, timeout):
    result = _command(docker, "status", "--format", "json", timeout=timeout)
    try:
        raw = json.loads(result.stdout) if len(result.stdout) <= 16384 else None
        state = raw.get("Status", raw.get("status")) if isinstance(raw, dict) else None
    except (ValueError, TypeError):
        state = None
    if state not in ("stopped", "running", "paused", "starting", "stopping") or result.returncode and state != "stopped":
        raise DesktopShutdownError("status")
    return state


def stopped_for_context(docker, windows=None, *, timeout=20):
    """Offline proof only for the local Desktop Linux pipe, never another daemon.

    A missing pipe alone is not proof. Context metadata is local, then the
    management CLI reports stopped, or an independently stopped WSL2 backend
    is verified when that management API has disappeared.
    """
    if not (os.name == "nt" if windows is None else windows) or not docker.executable:
        return False
    deadline = time.monotonic() + timeout
    # Keep enough time for both WSL list queries and native final checks. A
    # status plugin that remains in 'stopping' cannot consume that reserve.
    reserve = 8 if timeout >= 16 else 0
    def offline_proof():
        from .desktop_offline import stopped
        budget = min(8, max(0, deadline - time.monotonic()))
        _record("offline_budget", "available" if budget > 0 else "expired")
        return stopped(timeout=budget, wait=True)
    try:
        if timeout <= 0:
            return False
        endpoint = require_local_context(docker, timeout=min(4, timeout))
        if endpoint.lower() not in ("npipe:////./pipe/dockerdesktoplinuxengine", "npipe://./pipe/dockerdesktoplinuxengine"):
            _record("context", "unsupported_endpoint")
            return False
        _record("context", "desktop_linux")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _record("management", "deadline_expired")
                return False
            if remaining <= reserve:
                _record("management", "proof_budget_reserved")
                return offline_proof()
            try:
                state = _status(docker, min(4, remaining - reserve))
                _record("management", state)
                if state == "stopped":
                    return True
                if state != "stopping":
                    return False
            except DesktopShutdownError as error:
                _record("management", "timed_out" if error.code == "timeout" else "unavailable")
                return offline_proof()
            time.sleep(min(.25, max(0, deadline - time.monotonic() - reserve)))
    except (SPXError, OSError) as error:
        _record("context", "unavailable", error)
        return False


def stop_desktop(docker, progress=lambda message: None, timeout=60, windows=None):
    """Request normal asynchronous stop, then independently verify completion.

    Status failure alone is unknown. A successful stop is independently followed
    by stopped status or complete local WSL2 evidence. The same global deadline
    includes preflight, independent evidence and final polling.
    subprocess.run may reap its own timed-out CLI child, never Desktop/backend.
    """
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return {"docker_desktop_stopped": False, "not_applicable": True}
    if not docker.executable:
        raise DesktopShutdownError("missing")
    deadline = time.monotonic() + timeout
    def command(*args, limit=8):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DesktopShutdownError("timeout")
        return _command(docker, *args, timeout=min(limit, remaining))

    def status():
        try:
            return _status(docker, min(8, max(0, deadline - time.monotonic())))
        except DesktopShutdownError:
            # A manual/normal quit can remove the management API as well as
            # the engine pipe. Independently verify that exact local backend.
            from .desktop_offline import stopped
            _record("joint_management", "unavailable")
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    endpoint = require_local_context(docker, timeout=min(4, remaining))
                    remaining = deadline - time.monotonic()
                    supported = endpoint.lower() in ("npipe:////./pipe/dockerdesktoplinuxengine", "npipe://./pipe/dockerdesktoplinuxengine")
                    _record("joint_context", "desktop_linux" if supported else "unsupported_endpoint")
                    if supported and stopped(timeout=min(8, remaining), wait=True):
                        return "stopped"
                except (SPXError, OSError) as error:
                    _record("joint_context", "unavailable", error)
            raise

    progress("工作区与记录已收尾，正在读取 Docker Desktop 状态…")
    state = status()
    if state == "stopped":
        return {"docker_desktop_stopped": True, "already_stopped": True}
    if state != "stopping":
        progress("正在正常关闭 Docker Desktop；不会关闭其它 WSL 发行版…")
        seconds = max(1, min(10, int(deadline - time.monotonic())))
        try:
            result = command("stop", "--detach", "--timeout", str(seconds), limit=12)
            # Older management CLIs may not support --detach. Only a parser
            # rejection permits the existing normal synchronous command.
            if result.returncode and "unknown flag: --detach" in result.stderr.lower():
                seconds = max(1, min(30, int(deadline - time.monotonic() - 8)))
                result = command("stop", "--timeout", str(seconds), limit=seconds + 2)
        except DesktopShutdownError:
            # A CLI timeout/error may occur after the request was accepted.
            # Stopping permits polling; only stopped permits success.
            current = status()
            if current == "stopped":
                return {"docker_desktop_stopped": True, "already_stopped": False}
            if current != "stopping":
                raise
        else:
            if result.returncode:
                current = status()
                if current == "stopped":
                    return {"docker_desktop_stopped": True, "already_stopped": False}
                if current != "stopping":
                    raise DesktopShutdownError("stop")
    progress("正在确认 Docker Desktop 已停止…")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DesktopShutdownError("timeout")
        try:
            if status() == "stopped":
                return {"docker_desktop_stopped": True, "already_stopped": False}
        except DesktopShutdownError:
            # The management endpoint can briefly disappear during shutdown.
            # Keep polling within the same deadline, never infer stopped.
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(.5, remaining))
