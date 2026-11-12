"""Read-only proof for a fully closed local Docker Desktop WSL2 backend.

Used only when Desktop's management API cannot report a state. A missing
engine pipe is insufficient: require explicit WSL2 configuration, complete
process enumeration, the registered Docker distro to be absent from WSL's
running list, and repeat process/pipe observations before accepting the proof.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import time

from .docker_env import environment
from .process_metrics import desktop_processes

PIPE = r"\\.\pipe\dockerDesktopLinuxEngine"
DISTROS = frozenset(("docker-desktop", "docker-desktop-data"))


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


def stopped(timeout=8):
    """Return false on unknown/denied/unsupported evidence; emit no OS output."""
    if os.name != "nt" or timeout <= 0:
        return False
    deadline = time.monotonic() + timeout
    try:
        if not _wsl_enabled():
            return False
        kernel = _kernel()
        if not _desktop_absent() or not _pipe_absent(kernel):
            return False
        executable = _wsl_path(kernel)
        registered = _distributions(executable, False, deadline - time.monotonic())
        if "docker-desktop" not in registered:
            return False
        running = _distributions(executable, True, deadline - time.monotonic())
        if DISTROS & running or not running <= registered:
            return False
        return time.monotonic() < deadline and _desktop_absent() and _pipe_absent(kernel)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
        return False
