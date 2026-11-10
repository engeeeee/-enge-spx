"""Windows shell integration, kept separate from the portable control plane."""
import ctypes
import hashlib
import os
from pathlib import Path
import time

from .brand import APP_ID, ICONS as ASSETS, LEGACY_APP_ID


def restore_message():
    """A show-only request handled by Qt in the owning GUI process."""
    if os.name != "nt":
        return 0
    user = ctypes.windll.user32
    user.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
    user.RegisterWindowMessageW.restype = ctypes.c_uint
    return user.RegisterWindowMessageW(APP_ID + ".RestoreWindow")


def prepare_windows(dpi=True):
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
    if not dpi:
        return  # Qt manages per-monitor DPI for the native desktop interface.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


class WindowInstance:
    def __init__(self, home, legacy=False):
        self.handle = None
        identity = LEGACY_APP_ID if legacy else APP_ID
        self.key = identity + "." + hashlib.sha256(os.path.normcase(str(home)).encode()).hexdigest()[:16]

    def acquire(self):
        if os.name != "nt":
            return True
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        self.handle = kernel.CreateMutexW(None, False, "Local\\" + self.key)
        if not self.handle:
            return True
        if ctypes.get_last_error() != 183:
            return True
        user = ctypes.windll.user32
        user.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        user.GetPropW.restype = ctypes.c_void_p
        user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
        user.SendMessageTimeoutW.restype = ctypes.c_void_p
        message = restore_message()
        callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        found = []
        def visit(hwnd, _):
            if user.GetPropW(hwnd, self.key):
                found.append(hwnd)
                result = ctypes.c_size_t()
                acknowledged = message and user.SendMessageTimeoutW(hwnd, message, 0, 0, 2, 1000, ctypes.byref(result)) and result.value == 1
                if not acknowledged:
                    # Compatibility with an already running pre-0.10 GUI. New
                    # versions restore through QWidget, including its internal
                    # visibility state and resource/shortcut event handling.
                    user.ShowWindow(hwnd, 9)
                user.SetForegroundWindow(hwnd)
                return False
            return True
        for _ in range(15):
            user.EnumWindows(callback(visit), 0)
            if found:
                break
            time.sleep(.1)
        self.close()
        return False

    def register_hwnd(self, hwnd):
        if os.name == "nt":
            user = ctypes.windll.user32
            user.SetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p]
            user.SetPropW(hwnd, self.key, ctypes.c_void_p(1))

    def close(self):
        if self.handle:
            kernel = ctypes.windll.kernel32
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.handle)
            self.handle = None
