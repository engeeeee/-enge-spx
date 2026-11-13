"""Read-only proof for a fully closed local Docker Desktop WSL2 backend.

Used only when Desktop's management API cannot report a state. A missing
engine pipe is insufficient: require explicit WSL2 configuration, complete
process enumeration, the registered Docker distro to be absent from WSL's
running list, and repeat process/pipe observations before accepting the proof.
"""
import ctypes
import json
import logging
import os
from pathlib import Path
import subprocess
import time

from .docker_env import environment
from .process_metrics import desktop_processes
from .exit_diagnostics import add_check

PIPE = r"\\.\pipe\dockerDesktopLinuxEngine"
DISTROS = frozenset(("docker-desktop", "docker-desktop-data"))
log = logging.getLogger("enge_spx.gui")


def _record(stage, result, error=None):
    # Fixed stage/result codes only: never include settings, distro/process
    # names, command output, exception messages or user paths in GUI logs.
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    code = code if type(code) is int else 0
    log.info("desktop-offline-check stage=%s result=%s error_type=%s os_code=%s",
             stage, result, type(error).__name__ if error else "none", code)
    add_check("offline", stage, result, error)


def _kernel():
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True, winmode=0x00000800)
    kernel.WaitNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD]
    kernel.WaitNamedPipeW.restype = w.BOOL
    kernel.GetSystemDirectoryW.argtypes = [w.LPWSTR, w.UINT]
    kernel.GetSystemDirectoryW.restype = w.UINT
    return kernel


def _pipe_absent(kernel):
    ctypes.set_last_error(0)
    # A busy/inaccessible pipe is not absent. Never open or start the engine.
    return not kernel.WaitNamedPipeW(PIPE, 1) and ctypes.get_last_error() == 2


def _desktop_absent():
    return not any(row["scope"] == "desktop" for row in desktop_processes(strict=True))


def _wsl_enabled():
    roaming = os.environ.get("APPDATA")
    if not roaming or not Path(roaming).is_absolute():
        return False
    for name in ("settings-store.json", "settings.json"):
        path = Path(roaming) / "Docker" / name
        try:
            with path.open("rb") as stream:
                data = stream.read(1024 * 1024 + 1)
        except FileNotFoundError:
            continue
        if len(data) > 1024 * 1024:
            return False
        raw = json.loads(data.decode("utf-8-sig"))
        if not isinstance(raw, dict):
            return False
        values = [raw[key] for key in ("wslEngineEnabled", "WslEngineEnabled") if key in raw]
        # Older/newer settings may wrap the value. Missing or conflicting
        # values are unknown; never fall back to a stale legacy settings file.
        values = [value.get("value") if isinstance(value, dict) else value for value in values]
        return bool(values) and all(value is True for value in values)
    return False


def _wsl_path(kernel):
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError("Windows system directory is unavailable")
    path = Path(buffer.value) / "wsl.exe"
    if not path.is_absolute() or not path.is_file():
        raise OSError("Windows WSL command is unavailable")
    return str(path)


def _distributions(executable, running, timeout):
    if timeout <= 0:
        raise TimeoutError("Offline Desktop verification timed out")
    command = [executable, "--list", "--quiet"]
    if running:
        command.append("--running")
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, timeout=min(3, timeout),
                            env=environment(executable),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode or not isinstance(result.stdout, bytes) or len(result.stdout) > 65536:
        raise OSError("WSL distribution status is unavailable")
    raw = result.stdout
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-16-le" if b"\0" in raw else "utf-8-sig"
    text = raw.decode(encoding)
    names = [line.strip() for line in text.splitlines() if line.strip()]
    if any(any(ord(char) < 32 or ord(char) == 127 for char in name) for name in names):
        raise ValueError("Invalid WSL distribution status")
    return {name.casefold() for name in names}


def _observe(deadline):
    stage = "wsl2_configuration"
    try:
        if not _wsl_enabled():
            _record(stage, "not_confirmed")
            return False
        _record(stage, "confirmed")
        stage = "windows_api"
        kernel = _kernel()
        stage = "desktop_processes"
        if not _desktop_absent():
            _record(stage, "present")
            return False
        _record(stage, "absent")
        stage = "engine_pipe"
        if not _pipe_absent(kernel):
            _record(stage, "present_or_unreadable")
            return False
        _record(stage, "absent")
        stage = "wsl_executable"
        executable = _wsl_path(kernel)
        stage = "wsl_registered"
        registered = _distributions(executable, False, deadline - time.monotonic())
        if "docker-desktop" not in registered:
            _record(stage, "docker_distro_not_registered")
            return False
        _record(stage, "confirmed")
        stage = "wsl_running"
        running = _distributions(executable, True, deadline - time.monotonic())
        if DISTROS & running:
            _record(stage, "docker_distro_running")
            return False
        if not running <= registered:
            _record(stage, "inconsistent")
            return False
        _record(stage, "docker_distro_stopped")
        if time.monotonic() >= deadline:
            _record("deadline", "expired")
            return False
        stage = "final_desktop_processes"
        if not _desktop_absent():
            _record(stage, "present")
            return False
        stage = "final_engine_pipe"
        if not _pipe_absent(kernel):
            _record(stage, "present_or_unreadable")
            return False
        _record("complete", "verified")
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as error:
        _record(stage, "unavailable", error)
        return False


def stopped(timeout=8, *, wait=False):
    """Allow bounded teardown time; every accepted observation remains complete."""
    if os.name != "nt":
        _record("preflight", "unsupported_platform")
        return False
    if timeout <= 0:
        _record("preflight", "budget_expired")
        return False
    deadline = time.monotonic() + timeout
    while True:
        if _observe(deadline):
            return True
        if not wait:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _record("deadline", "expired")
            return False
        time.sleep(min(.25, remaining))
