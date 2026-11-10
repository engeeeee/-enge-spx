"""Read-only OS counters and optional public PID records; no process command lines."""
from contextlib import contextmanager
from functools import lru_cache
import ctypes
import os
from pathlib import Path
import time

from .state import SPXError

ACTIONS = {"guard": "网络安全监测", "forward": "本机代理中转", "relay": "浏览器显示服务"}


@lru_cache(maxsize=1)
def _windows():
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True, winmode=0x00000800)
    psapi = ctypes.WinDLL("psapi", use_last_error=True, winmode=0x00000800)
    class Memory(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]]
    class Process(ctypes.Structure):
        _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD), ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]
    class SystemMemory(ctypes.Structure):
        _fields_ = [("dwLength", w.DWORD), ("dwMemoryLoad", w.DWORD), *[(name, ctypes.c_ulonglong) for name in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.GetSystemTimes.argtypes = [ctypes.POINTER(w.FILETIME)] * 3
    kernel.GetSystemTimes.restype = w.BOOL
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(SystemMemory)]
    kernel.GlobalMemoryStatusEx.restype = w.BOOL
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [w.HANDLE, ctypes.POINTER(Process)]
        function.restype = w.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Memory), w.DWORD]
    psapi.GetProcessMemoryInfo.restype = w.BOOL
    return kernel, psapi, Memory, Process, SystemMemory


def _filetime(value):
    return value.dwLowDateTime | value.dwHighDateTime << 32


def process(pid):
    """Return cumulative CPU seconds, current RSS and a PID-reuse identity."""
    try:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        if os.name == "nt":
            from ctypes import wintypes as w
            kernel, psapi, Memory, _, _ = _windows()
            handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                created, exited, cpu_kernel, cpu_user = (w.FILETIME() for _ in range(4))
                memory = Memory()
                memory.cb = ctypes.sizeof(memory)
                if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)) or _filetime(exited) or not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                    return None
                return {"pid": pid, "created": _filetime(created), "cpu_seconds": (_filetime(cpu_kernel) + _filetime(cpu_user)) / 10**7, "memory_bytes": memory.WorkingSetSize, "private_bytes": memory.PrivateUsage}
            finally:
                kernel.CloseHandle(handle)
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "created": int(fields[19]), "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"), "memory_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"), "private_bytes": None}
    except (OSError, ValueError, IndexError):
        return None


def system():
    try:
        if os.name == "nt":
            from ctypes import wintypes as w
            kernel, _, _, _, SystemMemory = _windows()
            idle, cpu_kernel, cpu_user = (w.FILETIME() for _ in range(3))
            memory = SystemMemory()
            memory.dwLength = ctypes.sizeof(memory)
            if not kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)) or not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
                return None
            return {"cpu_total": _filetime(cpu_kernel) + _filetime(cpu_user), "cpu_idle": _filetime(idle), "memory_total": memory.ullTotalPhys, "memory_used": memory.ullTotalPhys - memory.ullAvailPhys}
        counters = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
        memory = {key: int(value.split()[0]) * 1024 for key, value in (row.split(":", 1) for row in Path("/proc/meminfo").read_text().splitlines())}
        return {"cpu_total": sum(counters), "cpu_idle": counters[3] + counters[4], "memory_total": memory["MemTotal"], "memory_used": memory["MemTotal"] - memory["MemAvailable"]}
    except (OSError, ValueError, KeyError, IndexError):
        return None


def desktop_processes():
    """Enumerate names/PIDs only; shared WSL memory is not app-owned memory."""
    if os.name != "nt":
        return []
    kernel, _, _, Process, _ = _windows()
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return []
    try:
        item = Process()
        item.dwSize = ctypes.sizeof(item)
        result = []
        available = kernel.Process32FirstW(snapshot, ctypes.byref(item))
        while available:
            name = item.szExeFile
            normalized = name.lower().removesuffix(".exe")
            if normalized in ("vmmem", "vmmemwsl", "docker desktop", "com.docker.backend", "com.docker.proxy", "vpnkit"):
                result.append({"pid": item.th32ProcessID, "name": name, "scope": "wsl" if normalized in ("vmmem", "vmmemwsl") else "desktop"})
            available = kernel.Process32NextW(snapshot, ctypes.byref(item))
        return result
    finally:
        kernel.CloseHandle(snapshot)


class Sampler:
    def __init__(self):
        self.previous = {}
        self.previous_system = None

    def sample(self, pid):
        value = process(pid)
        if value is None:
            self.previous.pop(pid, None)
            return {"pid": pid, "available": False, "cpu_percent": None, "memory_bytes": None}
        now = time.monotonic()
        previous = self.previous.get(pid)
        cpu = None
        if previous and previous[0] == value["created"] and now > previous[1]:
            cpu = max(0, (value["cpu_seconds"] - previous[2]) / (now - previous[1]) * 100)
        self.previous[pid] = (value["created"], now, value["cpu_seconds"])
        return {**value, "available": True, "cpu_percent": cpu}

    def host(self):
        value = system()
        if value is None:
            return {"available": False}
        cpu = None
        if self.previous_system:
            total = value["cpu_total"] - self.previous_system["cpu_total"]
            idle = value["cpu_idle"] - self.previous_system["cpu_idle"]
            if total > 0:
                cpu = max(0, min(100, (total - idle) / total * 100))
        self.previous_system = value
        return {**value, "available": True, "cpu_percent": cpu}


@contextmanager
def tracked(store, action):
    """Failure to register telemetry must never stop safety monitoring."""
    name = f"processes/{action}-{os.getpid()}.json"
    try:
        record = process(os.getpid())
        if action in ACTIONS and record:
            store.write(name, {"schema": 1, "action": action, "pid": record["pid"], "created": record["created"]})
    except Exception:
        pass
    try:
        yield
    finally:
        if action in ACTIONS:
            try:
                (store.home / name).unlink(missing_ok=True)
            except OSError:
                pass
