"""Owned Windows window backdrop only; no hooks, injection or new dependencies."""
import ctypes
from ctypes import wintypes
import os
import sys


class Accent(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint32), ("animation", ctypes.c_int)]


class Composition(ctypes.Structure):
    _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


def dpi_awareness():
    if os.name != 'nt':
        return 'platform-managed'
    try:
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetThreadDpiAwarenessContext.argtypes, user.GetThreadDpiAwarenessContext.restype = [], wintypes.HANDLE
        user.AreDpiAwarenessContextsEqual.argtypes, user.AreDpiAwarenessContextsEqual.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
        context = user.GetThreadDpiAwarenessContext()
        for value, label in ((-4, 'per-monitor-v2'), (-3, 'per-monitor'), (-2, 'system'), (-1, 'unaware'), (-5, 'unaware-gdi-scaled')):
            if user.AreDpiAwarenessContextsEqual(context, wintypes.HANDLE(value)):
                return label
    except (AttributeError, OSError, ValueError):
        pass
    return 'unavailable'


def moving_or_sizing():
    """Read this GUI thread's native modal state, without hooks or input polling."""
    if os.name != 'nt':
        return False
    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('flags', wintypes.DWORD),
                    *[(name, wintypes.HWND) for name in ('active', 'focus', 'capture', 'menu', 'move', 'caret')],
                    ('caret_rect', wintypes.RECT)]
    try:
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetGUIThreadInfo.argtypes, user.GetGUIThreadInfo.restype = [wintypes.DWORD, ctypes.POINTER(GuiThreadInfo)], wintypes.BOOL
        info = GuiThreadInfo()
        info.size = ctypes.sizeof(info)
        return bool(info.flags & 2) if user.GetGUIThreadInfo(0, ctypes.byref(info)) else None
    except (AttributeError, OSError):
        return None


def apply_acrylic(window, color, enabled=True):
    """Return the actual accepted backend, or an explicit opaque fallback."""
    if os.name != "nt":
        return "unsupported"
    try:
        hwnd = wintypes.HWND(int(window.winId()))
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.IsWindow.argtypes, user.IsWindow.restype = [wintypes.HWND], wintypes.BOOL
        if not user.IsWindow(hwnd):
            return "unsupported"
        if enabled:
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                    if winreg.QueryValueEx(key, "EnableTransparency")[0] == 0:
                        return "system-disabled"
            except OSError:
                pass
            class HighContrast(ctypes.Structure):
                _fields_ = [("size", wintypes.UINT), ("flags", wintypes.DWORD), ("scheme", wintypes.LPWSTR)]
            contrast = HighContrast()
            contrast.size = ctypes.sizeof(contrast)
            user.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
            user.SystemParametersInfoW.restype = wintypes.BOOL
            if user.SystemParametersInfoW(0x42, contrast.size, ctypes.byref(contrast), 0) and contrast.flags & 1:
                return "system-disabled"
        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        value = ctypes.c_int(3 if enabled else 1)  # DWMSBT_TRANSIENTWINDOW / NONE
        if sys.getwindowsversion().build >= 22621 and dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value)) >= 0:
            return "system-acrylic" if enabled else "solid"
        # Older Windows exposes AccentPolicy through this optional entry point.
        # Guard the ABI and BOOL result; unavailable policies stay opaque.
        function = getattr(user, "SetWindowCompositionAttribute", None)
        if function is None or sys.getwindowsversion().build < 17763:
            return "unsupported"
        function.argtypes, function.restype = [wintypes.HWND, ctypes.POINTER(Composition)], wintypes.BOOL
        # The client already supplies the user's tint/opacity. A second 80%
        # native tint made the old material almost opaque and muddy.
        tint = color.red() | color.green() << 8 | color.blue() << 16 | 0x01000000
        accent = Accent(4 if enabled else 0, 2, tint, 0)
        composition = Composition(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        if function(hwnd, ctypes.byref(composition)):
            return "accent-acrylic" if enabled else "solid"
    except (AttributeError, OSError, ValueError):
        pass
    return "unsupported"


def configure_frame(window):
    """Own HWND only: keep OS move/resize semantics beneath custom Qt chrome."""
    if os.name != 'nt':
        return False
    try:
        hwnd = wintypes.HWND(int(window.winId()))
        user = ctypes.WinDLL('user32', use_last_error=True)
        get, put = user.GetWindowLongPtrW, user.SetWindowLongPtrW
        get.argtypes, get.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
        put.argtypes, put.restype = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
        # No standard caption: NCCALCSIZE and NCHITTEST are owned by this window.
        original = get(hwnd, -16)
        ctypes.set_last_error(0)
        previous = put(hwnd, -16, original | 0x40000 | 0x80000 | 0x20000 | 0x10000)
        if previous == 0 and ctypes.get_last_error():
            return False
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos.restype = wintypes.BOOL
        if not user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37):
            return False
        return True
    except (AttributeError, OSError, ValueError):
        return False


def client_point(window, lparam):
    """Convert signed physical NCHITTEST coordinates into this HWND's client."""
    from PySide6.QtCore import QPoint
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindowRect.argtypes, user.GetWindowRect.restype = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL
    user.GetClientRect.argtypes, user.GetClientRect.restype = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL
    user.ScreenToClient.argtypes, user.ScreenToClient.restype = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL
    hwnd = wintypes.HWND(int(window.winId()))
    bounds = wintypes.RECT()
    point = wintypes.POINT(ctypes.c_short(lparam & 0xffff).value, ctypes.c_short((lparam >> 16) & 0xffff).value)
    if not user.GetClientRect(hwnd, ctypes.byref(bounds)) or not user.ScreenToClient(hwnd, ctypes.byref(point)):
        return None
    width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
    if width <= 0 or height <= 0:
        return None
    return QPoint(round(point.x * window.width() / width), round(point.y * window.height() / height))


def adjust_maximized_client(window, lparam):
    """Keep custom chrome inside the work area, including the invisible resize rim."""
    if window.isFullScreen():
        return
    user = ctypes.WinDLL('user32', use_last_error=True)
    hwnd = wintypes.HWND(int(window.winId()))
    user.IsZoomed.argtypes, user.IsZoomed.restype = [wintypes.HWND], wintypes.BOOL
    if not user.IsZoomed(hwnd):
        return
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    user.MonitorFromWindow.argtypes, user.MonitorFromWindow.restype = [wintypes.HWND, wintypes.DWORD], wintypes.HANDLE
    user.GetMonitorInfoW.argtypes, user.GetMonitorInfoW.restype = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)], wintypes.BOOL
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    if user.GetMonitorInfoW(user.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        # NCCALCSIZE_PARAMS starts with its proposed client RECT.
        rect = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
        rect.left, rect.top = max(rect.left, info.work.left), max(rect.top, info.work.top)
        rect.right, rect.bottom = min(rect.right, info.work.right), min(rect.bottom, info.work.bottom)
