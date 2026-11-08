"""Prepare a workspace without blocking the GUI or changing global Docker settings."""
from __future__ import annotations

import os
import platform
import subprocess
import threading
import time

from .downloads import DownloadPaused
from .state import SPXError
from . import __version__

DOCKER_INSTALL_URL = "https://docs.docker.com/desktop/setup/install/windows-install/"


class DockerUnavailable(SPXError):
    pass


class DockerContextUnavailable(DockerUnavailable):
    pass


class DockerConfigurationError(SPXError):
    pass


class StartupIssue(SPXError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise DownloadPaused("已取消准备。已经启动的 Docker Desktop 会继续运行，已有环境和下载均保留。")


def diagnostics(store, docker_info=None, startup_error=None):
    settings = store.settings()
    state = store.read("runtime.json", {})
    relay = settings["relay"]
    info = docker_info or {}
    return {"app": "ENGE SPX", "version": __version__, "system": platform.system(), "system_release": platform.release(), "architecture": platform.machine(), "docker_version": info.get("docker"), "docker_architecture": info.get("architecture"), "docker_context": settings["context"], "runtime_recorded": len(store.read("images.json", {})) == 3, "phase": state.get("phase", "stopped"), "line_mode": relay.get("mode", "local") if relay.get("enabled") else "disabled", "proxy_downloads": relay.get("downloads", True), "auto_start_docker": settings.get("auto_start_docker", True), "startup_error": startup_error}


def launch_desktop(docker):
    """Prefer Docker's supported management CLI; support older Desktop versions."""
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if docker.executable:
        try:
            # Management commands address the local Desktop, even before its
            # desktop-linux context exists. Never change the user's default context.
            result = subprocess.run([docker.executable, "desktop", "start", "--detach", "--timeout", "15"], capture_output=True, timeout=20, env=docker.environment(), creationflags=hidden)
            if result.returncode == 0:
                return "cli"
        except (OSError, subprocess.TimeoutExpired):
            pass
    application = docker.desktop_app(docker.executable)
    if not application:
        raise StartupIssue("docker_missing", "未找到 Docker Desktop。请先安装 Docker Desktop、完成首次初始化，再点击“一键准备”。")
    try:
        process = subprocess.Popen([str(application)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=docker.environment(), creationflags=hidden)
    except OSError as error:
        raise StartupIssue("launch_failed", "无法打开 Docker Desktop，请检查安装目录或在 Windows 中打开一次后重试。") from error
    # Keep and reap the launcher without waiting in the UI worker or terminating
    # Desktop when the user cancels preparation or closes ENGE SPX.
    threading.Thread(target=process.wait, daemon=True).start()
    return "application"


def ensure_docker(engine, progress=lambda value: None, cancel=None, auto_start=True, timeout=180, windows=None):
    windows = os.name == "nt" if windows is None else windows
    deadline, launched = time.monotonic() + timeout, False
    while True:
        cancelled(cancel)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StartupIssue("docker_timeout", "等待 Docker Linux 引擎超时。请打开 Docker Desktop，完成许可、WSL 2 或首次初始化提示，确认使用 Linux containers 后重试。")
        progress({"stage": "docker_wait" if launched else "docker_check", "message": "等待 Docker Linux 引擎就绪；首次使用请在 Docker 窗口完成初始化…" if launched else "正在检测 Docker Desktop 和 Linux 引擎…"})
        if not engine.docker.executable:
            raise StartupIssue("docker_missing", "未找到 Docker 命令行工具。请先安装或修复 Docker Desktop，再点击“一键准备”。")
        try:
            info = engine.doctor(timeout=min(3, max(.2, remaining / 2)))
        except DockerConfigurationError as error:
            raise StartupIssue("docker_configuration", str(error)) from error
        except DockerContextUnavailable as error:
            if engine.docker.context not in ("desktop-linux", "default"):
                raise StartupIssue("docker_context", "所选 Docker 上下文不可用。请在偏好设置检查名称，Docker Desktop 通常使用 desktop-linux。") from error
        except DockerUnavailable:
            pass
        else:
            cancelled(cancel)
            progress({"stage": "docker_ready", "message": "Docker Linux 引擎已就绪。"})
            return info
        if not launched:
            if not auto_start or not windows:
                raise StartupIssue("docker_stopped", "Docker 引擎尚未就绪。请启动本机 Docker，或在 Windows 中点击“一键准备”自动启动 Docker Desktop。")
            cancelled(cancel)
            progress({"stage": "docker_start", "message": "正在启动 Docker Desktop…"})
            launch_desktop(engine.docker)
            launched = True
        delay = min(1, max(0, deadline - time.monotonic()))
        if cancel is not None:
            cancel.wait(delay)
        else:
            time.sleep(delay)


def prepare_workspace(engine, settings=None, progress=lambda value: None, cancel=None, auto_start=True, install=True, check=True, source=False):
    """Start Desktop, verify/install images, then stop at explicit exit review."""
    cancelled(cancel)
    if settings is not None:
        context = settings[2]
        if not context.strip() or context.startswith("-"):
            raise StartupIssue("docker_context", "请填写有效的本机 Docker 上下文名称。")
        if engine.store.settings()["context"] != context and engine.store.read("images.json"):
            raise StartupIssue("docker_context", "已有运行环境不能切换 Docker 上下文，请保留原上下文或使用独立数据目录。")
        engine.docker.context = context
    info = ensure_docker(engine, progress, cancel, auto_start)
    if settings is not None:
        engine.save_settings(*settings)
    cancelled(cancel)
    progress({"stage": "runtime_check", "message": "正在核验已有运行环境…"})
    try:
        engine.image_ids()
        installed = True
    except SPXError:
        installed = False
    if not installed or source and install:
        if not install:
            return {"phase": "needs_runtime", "docker": info, "runtime": False}
        progress({"stage": "runtime_install", "message": "正在根据本地配方构建运行环境…" if source else "首次使用需要获取运行环境，正在准备下载和安装…"})
        if source:
            engine.install(progress, cancel)
        else:
            engine.install_prebuilt(progress, cancel)
        engine.image_ids()
    cancelled(cancel)
    if not check:
        return {"phase": "prepared", "docker": info, "runtime": True}
    if not engine.store.settings()["selected"]:
        progress({"stage": "configure", "message": "运行环境已准备好。下一步添加落地代理，并按需配置前置线路。"})
        return {"phase": "needs_configuration", "docker": info, "runtime": True}
    progress({"stage": "connection_check", "message": "正在核对线路和落地出口，请等待检查完成…"})
    # A prepared environment never silently accepts an IP change or confirms a route.
    if engine.store.read("runtime.json", {}).get("phase") == "ready":
        with engine.store.lock():
            evidence = engine.ready().get("evidence")
        phase = "ready"
    else:
        evidence = engine.check()
        phase = "review"
    cancelled(cancel)
    progress({"stage": "review" if phase == "review" else "ready", "message": "请核对线路和落地出口，再确认启用。" if phase == "review" else "工作环境已就绪。"})
    return {"phase": phase, "docker": info, "runtime": True, "evidence": evidence}
