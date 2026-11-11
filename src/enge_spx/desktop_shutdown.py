"""Explicit Windows Desktop shutdown, separate from owner-scoped Engine.stop."""
import json
import os
import subprocess
import time

from .docker_env import environment
from .state import SPXError

PREFERENCES = "exit-preferences.json"


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
        super().__init__(messages[code] + " 工作区已停止；可在设置中取消联合关闭并保存，再仅退出 ENGE SPX。")
        self.code = code


def stop_desktop(docker, progress=lambda message: None, timeout=60, windows=None):
    """Use only the supported, synchronous stop; never start or force Desktop.

    Status failure is unknown, not stopped. A successful stop is independently
    followed by a stopped status. The bound includes preflight and final polling.
    subprocess.run may reap its own timed-out CLI child, never Desktop/backend.
    """
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return {"docker_desktop_stopped": False, "not_applicable": True}
    if not docker.executable:
        raise DesktopShutdownError("missing")
    deadline = time.monotonic() + timeout
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process_environment = environment(docker.executable)

    def command(*args, limit=8):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DesktopShutdownError("timeout")
        try:
            # Management addresses the local Desktop, never a selected context.
            return subprocess.run([docker.executable, "desktop", *args], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=min(limit, remaining), env=process_environment,
                                  creationflags=hidden, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise DesktopShutdownError("timeout") from None
        except OSError:
            raise DesktopShutdownError("status" if args[0] == "status" else "stop") from None

    def status():
        result = command("status", "--format", "json")
        try:
            raw = json.loads(result.stdout) if len(result.stdout) <= 16384 else None
            state = raw.get("Status", raw.get("status")) if isinstance(raw, dict) else None
        except (ValueError, TypeError):
            state = None
        if state not in ("stopped", "running", "paused", "starting", "stopping"):
            raise DesktopShutdownError("status")
        if result.returncode and state != "stopped":
            raise DesktopShutdownError("status")
        return state

    progress("工作区与记录已收尾，正在读取 Docker Desktop 状态…")
    state = status()
    if state == "stopped":
        return {"docker_desktop_stopped": True, "already_stopped": True}
    if state != "stopping":
        progress("正在正常关闭 Docker Desktop；不会关闭其它 WSL 发行版…")
        seconds = max(1, min(45, int(deadline - time.monotonic())))
        try:
            result = command("stop", "--timeout", str(seconds), limit=50)
        except DesktopShutdownError:
            # A CLI timeout/error may occur after the request was accepted. Only
            # explicit stopped evidence can turn that result into success.
            if status() != "stopped":
                raise
            return {"docker_desktop_stopped": True, "already_stopped": False}
        else:
            if result.returncode:
                if status() != "stopped":
                    raise DesktopShutdownError("stop")
                return {"docker_desktop_stopped": True, "already_stopped": False}
    progress("正在确认 Docker Desktop 已停止…")
    while status() != "stopped":
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DesktopShutdownError("timeout")
        time.sleep(min(.5, remaining))
    return {"docker_desktop_stopped": True, "already_stopped": False}
