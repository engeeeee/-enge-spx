"""Owned Windows window backdrop only; no hooks, injection or new dependencies."""
import ctypes
from ctypes import wintypes
import os
import sys


class Accent(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint32), ("animation", ctypes.c_int)]


class Composition(ctypes.Structure):
    _fields_ = [("attribute", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


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
        value = ctypes.c_int(3 if enabled else 1)  # DWMSBT_TRANSIENTWINDOW / NONE
        if sys.getwindowsversion().build >= 22621 and dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value)) >= 0:
            return "system-acrylic" if enabled else "solid"
        # Older Windows exposes AccentPolicy through this optional entry point.
        # Guard the ABI and BOOL result; unavailable policies stay opaque.
        function = getattr(user, "SetWindowCompositionAttribute", None)
        if function is None or sys.getwindowsversion().build < 17763:
            return "unsupported"
        function.argtypes, function.restype = [wintypes.HWND, ctypes.POINTER(Composition)], wintypes.BOOL
        tint = color.red() | color.green() << 8 | color.blue() << 16 | 0xCC000000
        accent = Accent(4 if enabled else 0, 2, tint, 0)
        composition = Composition(19, ctypes.cast(ctypes.byref(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        if function(hwnd, ctypes.byref(composition)):
            return "accent-acrylic" if enabled else "solid"
    except (AttributeError, OSError, ValueError):
        pass
    return "unsupported"
