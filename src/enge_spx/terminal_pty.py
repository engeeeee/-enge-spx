"""Owned ConPTY process, with a POSIX PTY backend for repeatable Linux tests.

Only the child docker exec client is stopped; this module cannot stop Docker,
kill a process by window title, or send input outside its own pipe handles.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
import subprocess
import threading

from .state import SPXError


class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR),
                ("dwX", w.DWORD), ("dwY", w.DWORD), ("dwXSize", w.DWORD), ("dwYSize", w.DWORD),
                ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


class _STARTUPINFOEX(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFO), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESSINFO(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


class WindowsPTY:
    def __init__(self, command, env, cwd, columns=110, rows=32):
        if os.name != "nt":
            raise SPXError("ConPTY 需要 Windows 10 1809 或更新版本。")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        api = self.api
        signatures = {
            "CreatePipe": ([ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), ctypes.c_void_p, w.DWORD], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreatePseudoConsole": ([_COORD, w.HANDLE, w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], ctypes.c_long),
            "ResizePseudoConsole": ([w.HANDLE, _COORD], ctypes.c_long),
            "ClosePseudoConsole": ([w.HANDLE], None),
            "InitializeProcThreadAttributeList": ([ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)], w.BOOL),
            "UpdateProcThreadAttribute": ([ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], w.BOOL),
            "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
            "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(_STARTUPINFOEX), ctypes.POINTER(_PROCESSINFO)], w.BOOL),
            "ReadFile": ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            "WriteFile": ([w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p], w.BOOL),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        }
        for name, (args, result) in signatures.items():
            try:
                fn = getattr(api, name)
            except AttributeError as error:
                raise SPXError("系统不支持 ConPTY，请升级 Windows 或选择外部终端（仅原有粘贴）。") from error
            fn.argtypes, fn.restype = args, result
        self.input = self.output = self.console = self.process = None
        self.closed = threading.Event()
        self.write_lock = threading.Lock()
        held, attributes = [], None
        try:
            ir, iw, ore, ow, pc = (w.HANDLE() for _ in range(5))
            if not api.CreatePipe(ctypes.byref(ir), ctypes.byref(iw), None, 0):
                raise OSError("pipe")
            held.extend((ir, iw))
            if not api.CreatePipe(ctypes.byref(ore), ctypes.byref(ow), None, 0):
                raise OSError("pipe")
            held.extend((ore, ow))
            if api.CreatePseudoConsole(_COORD(columns, rows), ir, ow, 0, ctypes.byref(pc)) < 0:
                raise OSError("pseudoconsole")
            self.console = pc
            size = ctypes.c_size_t()
            api.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            attributes = ctypes.cast(buffer, ctypes.c_void_p)
            if not api.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
                attributes = None
                raise OSError("attributes")
            if not api.UpdateProcThreadAttribute(attributes, 0, 0x00020016, pc, ctypes.sizeof(w.HANDLE), None, None):
                raise OSError("attributes")
            startup, info = _STARTUPINFOEX(), _PROCESSINFO()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            # Match Windows Terminal's launcher. Without this, a parent whose
            # stdio is redirected (CI, GUI/frozen launch) can have its pipe
            # handles duplicated into the child instead of ConPTY handles.
            # Null standard handles are recreated for the attached console.
            startup.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
            startup.lpAttributeList = attributes
            env_text = "\0".join(key + "=" + value for key, value in sorted(env.items(), key=lambda pair: pair[0].casefold())) + "\0\0"
            block = ctypes.create_unicode_buffer(env_text, len(env_text.encode("utf-16-le")) // 2 + 1)
            cmd_text = subprocess.list2cmdline(command)
            commandline = ctypes.create_unicode_buffer(cmd_text, len(cmd_text.encode("utf-16-le")) // 2 + 1)
            if not api.CreateProcessW(command[0], commandline, None, None, False, 0x00080000 | 0x00000400, block, str(cwd), ctypes.byref(startup), ctypes.byref(info)):
                raise OSError("process")
            api.CloseHandle(info.hThread)
            self.process = info.hProcess
            self.pid = info.dwProcessId
            self.input, self.output = iw, ore
            held.remove(iw)
            held.remove(ore)
        except OSError as error:
            self.close()
            raise SPXError("无法建立受控终端，请检查 Windows 版本或进程访问权限。") from error
        finally:
            if attributes:
                api.DeleteProcThreadAttributeList(attributes)
            for handle in held:
                api.CloseHandle(handle)

    def read(self, size=16384):
        handle = self.output
        if not handle:
            return b""
        buffer, count = ctypes.create_string_buffer(size), w.DWORD()
        if not self.api.ReadFile(handle, buffer, size, ctypes.byref(count), None):
            return b""
        return buffer.raw[:count.value]

    def write(self, data):
        with self.write_lock:
            offset = 0
            while offset < len(data) and not self.closed.is_set():
                count = w.DWORD()
                block = data[offset:offset + 16384]
                if not self.api.WriteFile(self.input, block, len(block), ctypes.byref(count), None) or not count.value:
                    raise SPXError("终端连接已结束，未发送输入。")
                offset += count.value

    def resize(self, columns, rows):
        if not self.closed.is_set():
            self.api.ResizePseudoConsole(self.console, _COORD(columns, rows))

    def poll(self):
        result = w.DWORD()
        if self.process and self.api.GetExitCodeProcess(self.process, ctypes.byref(result)):
            return None if result.value == 259 else result.value
        return 0

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if self.input:
            self.api.CloseHandle(self.input)
            self.input = None
        if self.process:
            if self.poll() is None:
                self.api.TerminateProcess(self.process, 1)
                self.api.WaitForSingleObject(self.process, 2000)
            self.api.CloseHandle(self.process)
            self.process = None
        # The output reader continues draining while ClosePseudoConsole runs.
        if self.console:
            self.api.ClosePseudoConsole(self.console)
            self.console = None
        if self.output:
            self.api.CloseHandle(self.output)
            self.output = None


class PosixPTY:
    """Development/integration backend, not a Windows Terminal emulation shim."""
    def __init__(self, command, env, cwd, columns=110, rows=32):
        import fcntl
        import pty
        import struct
        import termios
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        self.process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd,
                                        preexec_fn=lambda: os.login_tty(slave), close_fds=True)
        self.pid = self.process.pid
        os.close(slave)
        self.closed = threading.Event()

    def read(self, size=16384):
        try:
            return os.read(self.master, size)
        except OSError:
            return b""

    def write(self, data):
        while data and not self.closed.is_set():
            data = data[os.write(self.master, data):]

    def resize(self, columns, rows):
        import fcntl
        import struct
        import termios
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))

    def poll(self):
        return self.process.poll()

    def close(self):
        if not self.closed.is_set():
            self.closed.set()
            if self.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            os.close(self.master)


def start(command, env, cwd, columns=110, rows=32):
    return (WindowsPTY if os.name == "nt" else PosixPTY)(command, env, cwd, columns, rows)
