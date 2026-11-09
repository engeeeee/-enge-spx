"""Custom window chrome with native Windows move/resize and taskbar behavior."""
from __future__ import annotations

import ctypes
import os
import tkinter as tk

from . import theme
from .brand import APP_NAME, ICONS

HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
HTTOPLEFT, HTTOPRIGHT, HTBOTTOM = 13, 14, 15
HTBOTTOMLEFT, HTBOTTOMRIGHT = 16, 17


def edge_hit(x, y, width, height, border=7, maximized=False, resizable=True):
    if maximized or not resizable or x < 0 or y < 0 or x >= width or y >= height:
        return HTCLIENT
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    if top:
        return HTTOPLEFT if left else HTTOPRIGHT if right else HTTOP
    if bottom:
        return HTBOTTOMLEFT if left else HTBOTTOMRIGHT if right else HTBOTTOM
    return HTLEFT if left else HTRIGHT if right else HTCLIENT


def resized(start, edge, dx, dy, minimum):
    x, y, width, height = start
    right, bottom = x + width, y + height
    if edge in (HTLEFT, HTTOPLEFT, HTBOTTOMLEFT):
        x = min(x + dx, right - minimum[0])
        width = right - x
    elif edge in (HTRIGHT, HTTOPRIGHT, HTBOTTOMRIGHT):
        width = max(minimum[0], width + dx)
    if edge in (HTTOP, HTTOPLEFT, HTTOPRIGHT):
        y = min(y + dy, bottom - minimum[1])
        height = bottom - y
    elif edge in (HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT):
        height = max(minimum[1], height + dy)
    return x, y, width, height


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class Rect(ctypes.Structure):
    _fields_ = [(key, ctypes.c_int32) for key in ("left", "top", "right", "bottom")]


class MinMaxInfo(ctypes.Structure):
    _fields_ = [(key, Point) for key in ("reserved", "max_size", "max_position", "min_track", "max_track")]


class MonitorInfo(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("monitor", Rect), ("work", Rect), ("flags", ctypes.c_uint32)]


class NativeFrame:
    def __init__(self, root, resizable=True):
        self.root, self.resizable = root, resizable
        self.active = False
        self.old_proc = None
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.user.GetAncestor.restype = ctypes.c_void_p
        self.user.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        self.user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(Rect)]
        self.user.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(Rect)]
        self.user.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(Point)]
        self.user.IsZoomed.argtypes = [ctypes.c_void_p]
        self.user.IsIconic.argtypes = [ctypes.c_void_p]
        self.user.IsWindow.argtypes = [ctypes.c_void_p]
        self.user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self.user.SendMessageW.restype = ctypes.c_ssize_t
        self.user.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        self.user.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.user.MonitorFromWindow.restype = ctypes.c_void_p
        self.user.MonitorFromRect.argtypes = [ctypes.POINTER(Rect), ctypes.c_uint]
        self.user.MonitorFromRect.restype = ctypes.c_void_p
        self.user.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]
        self.user.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        self.user.GetDpiForWindow.restype = ctypes.c_uint
        root.update_idletasks()
        requested_width, requested_height = root.winfo_width(), root.winfo_height()
        self.hwnd = self.user.GetAncestor(root.winfo_id(), 2)
        if not self.hwnd:
            raise OSError("Window handle is unavailable")
        # Keep native shell styles: minimizing, keyboard moves, taskbar and
        # resizing still belong to Windows; only the non-client paint is removed.
        if resizable:
            style = self.user.GetWindowLongPtrW(self.hwnd, -16)
            self.user.SetWindowLongPtrW(self.hwnd, -16, style | 0x00CF0000)
            extended = self.user.GetWindowLongPtrW(self.hwnd, -20)
            self.user.SetWindowLongPtrW(self.hwnd, -20, (extended | 0x00040000) & ~0x00000080)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
        self.callback = callback_type(self._message)
        ctypes.set_last_error(0)
        previous = self.user.SetWindowLongPtrW(self.hwnd, -4, ctypes.cast(self.callback, ctypes.c_void_p).value)
        if not previous:
            raise ctypes.WinError(ctypes.get_last_error())
        self.old_proc, self.active = previous, True
        try:
            self._dwm()
            if resizable:
                area = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
                self.user.GetMonitorInfoW(self.user.MonitorFromWindow(self.hwnd, 2), ctypes.byref(area))
                width = min(requested_width, max(320, area.work.right - area.work.left - 20))
                height = min(requested_height, max(240, area.work.bottom - area.work.top - 20))
                minimum = root.minsize()
                root.minsize(min(minimum[0], width), min(minimum[1], height))
                x = area.work.left + (area.work.right - area.work.left - width) // 2
                y = area.work.top + (area.work.bottom - area.work.top - height) // 2
                self.user.SetWindowPos(self.hwnd, None, x, y, width, height, 0x0034)
            else:
                # Removing a caption must not add its old height to a dialog.
                self.user.SetWindowPos(self.hwnd, None, 0, 0, requested_width, requested_height, 0x0036)
        except Exception:
            self.close()
            raise

    def _dwm(self):
        try:
            dwm = ctypes.WinDLL("dwmapi")
            dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            # Ignore unsupported attributes on older Windows versions.
            for attribute, value in ((20, 1), (33, 2), (34, 0xFFFFFFFE)):
                data = ctypes.c_uint32(value)
                dwm.DwmSetWindowAttribute(self.hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
        except (OSError, AttributeError):
            pass

    def _message(self, hwnd, message, wparam, lparam):
        try:
            if message == 0x0083:  # WM_NCCALCSIZE: use the full window as client.
                if self.maximized():
                    # Maximized overlapped windows retain invisible sizing
                    # margins outside the monitor. Keep custom chrome visible
                    # by clipping the client to the proposed monitor work area.
                    proposed = ctypes.cast(lparam, ctypes.POINTER(Rect))
                    info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
                    monitor = self.user.MonitorFromRect(proposed, 2)
                    if self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
                        rect = proposed.contents
                        rect.left = max(rect.left, info.work.left)
                        rect.top = max(rect.top, info.work.top)
                        rect.right = min(rect.right, info.work.right)
                        rect.bottom = min(rect.bottom, info.work.bottom)
                return 0
            if message == 0x0084:  # WM_NCHITTEST; signed coordinates support left monitors.
                x, y = ctypes.c_int16(lparam & 0xFFFF).value, ctypes.c_int16((lparam >> 16) & 0xFFFF).value
                rect = Rect()
                self.user.GetWindowRect(hwnd, ctypes.byref(rect))
                border = max(6, round(7 * (self.user.GetDpiForWindow(hwnd) or 96) / 96))
                hit = edge_hit(x - rect.left, y - rect.top, rect.right - rect.left, rect.bottom - rect.top, border, self.maximized(), self.resizable)
                if hit != HTCLIENT:
                    return hit
            if message == 0x0024:  # WM_GETMINMAXINFO: maximize into this monitor's work area.
                result = self.user.CallWindowProcW(self.old_proc, hwnd, message, wparam, lparam)
                info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
                if self.user.GetMonitorInfoW(self.user.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
                    target = ctypes.cast(lparam, ctypes.POINTER(MinMaxInfo)).contents
                    target.max_position.x = info.work.left - info.monitor.left
                    target.max_position.y = info.work.top - info.monitor.top
                    target.max_size.x = info.work.right - info.work.left
                    target.max_size.y = info.work.bottom - info.work.top
                return result
        except Exception:
            # An exception must never unwind through the native window callback.
            pass
        return self.user.CallWindowProcW(self.old_proc, hwnd, message, wparam, lparam)

    def maximized(self):
        return bool(self.user.IsZoomed(self.hwnd))

    def minimize(self):
        self.user.ShowWindow(self.hwnd, 6)

    def restore(self):
        self.user.ShowWindow(self.hwnd, 9)

    def toggle_maximize(self):
        self.user.ShowWindow(self.hwnd, 9 if self.maximized() else 3)

    def drag(self, hit, x, y):
        self.user.ReleaseCapture()
        packed = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
        self.user.SendMessageW(self.hwnd, 0x00A1, hit, packed)

    def close(self):
        if self.active and self.user.IsWindow(self.hwnd):
            self.user.SetWindowLongPtrW(self.hwnd, -4, self.old_proc)
        self.active = False


class WindowFrame:
    def __init__(self, root, title=APP_NAME, close=None, resizable=True):
        self.root, self.resizable = root, resizable
        self.native = None
        self._drag = None
        self._normal_geometry = None
        self._maximized = False
        self._fallback_minimized = False
        root.configure(background=theme.BORDER)
        self.shell = tk.Frame(root, background=theme.BG)
        self.shell.pack(fill="both", expand=True, padx=1, pady=1)
        self.titlebar = tk.Frame(self.shell, background=theme.SIDEBAR, height=44)
        self.titlebar.pack(fill="x")
        self.titlebar.pack_propagate(False)
        self.icon = tk.PhotoImage(file=str(ICONS / "logo-32.png")).subsample(2)
        self.mark = tk.Label(self.titlebar, image=self.icon, background=theme.SIDEBAR)
        self.mark.pack(side="left", padx=(18, 8))
        self.title = tk.Label(self.titlebar, text=title, background=theme.SIDEBAR, foreground=theme.INK, font=(theme.FONT, 10, "bold"), padx=0)
        self.title.pack(side="left")
        self.status = tk.Label(self.titlebar, text="AI 编程隔离工作台" if resizable else "", background=theme.SIDEBAR, foreground=theme.MUTED, font=(theme.FONT, 9))
        self.status.pack(side="left", padx=14)
        self.controls = {}
        actions = [("close", "×", close or root.destroy)]
        if resizable:
            actions += [("maximize", "□", self.toggle_maximize), ("minimize", "—", self.minimize)]
        for name, glyph, action in actions:
            button = tk.Button(self.titlebar, name=name, text=glyph, command=action, background=theme.SIDEBAR, foreground=theme.MUTED, activebackground="#A33F35" if name == "close" else theme.HOVER, activeforeground=theme.INK, borderwidth=0, highlightthickness=0, relief="flat", width=4, font=(theme.FONT, 14), takefocus=True)
            button.pack(side="right", fill="y")
            button.bind("<Enter>", lambda event, b=button, n=name: b.configure(background="#A33F35" if n == "close" else theme.HOVER, foreground=theme.INK))
            button.bind("<Leave>", lambda event, b=button: b.configure(background=theme.SIDEBAR, foreground=theme.MUTED))
            self.controls[name] = button
        tk.Frame(self.shell, background=theme.BORDER, height=1).pack(fill="x")
        self.content = tk.Frame(self.shell, background=theme.BG)
        self.content.pack(fill="both", expand=True)
        for widget in (self.titlebar, self.mark, self.title, self.status):
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._move)
            widget.bind("<Double-Button-1>", self._double_click)
        if os.name == "nt":
            try:
                self.native = NativeFrame(root, resizable)
            except (OSError, AttributeError):
                root.overrideredirect(True)
        else:
            root.overrideredirect(True)
        if resizable:
            self._resize_handles()
        root.bind("<Configure>", self._configured, add="+")
        root.bind("<Map>", self._mapped, add="+")
        root.bind("<Destroy>", self._destroyed, add="+")
        def close_key(event):
            (close or root.destroy)()
            return "break"
        root.bind("<Alt-F4>", close_key, add="+")
        root._spx_frame = self  # Keep the native callback alive for the HWND lifetime.

    def set_status(self, text, color=theme.MUTED):
        self.status.configure(text=text, foreground=color)

    def center(self, parent, width, height):
        self.root.geometry(f"{width}x{height}")
        self.root.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        if self.native:
            self.native.user.SetWindowPos(self.native.hwnd, None, x, y, width, height, 0x0014)
        else:
            self.root.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def maximized(self):
        return self.native.maximized() if self.native else self._maximized

    def minimize(self):
        if self.native:
            self.native.minimize()
        else:
            self._fallback_minimized = True
            self.root.overrideredirect(False)
            self.root.iconify()

    def restore(self):
        if self.native:
            self.native.restore()
        else:
            self.root.deiconify()
            if self._maximized:
                self.toggle_maximize()

    def toggle_maximize(self):
        if not self.resizable:
            return
        if self.native:
            self.native.toggle_maximize()
        elif self._maximized:
            self.root.geometry(self._normal_geometry)
            self._maximized = False
        else:
            self._normal_geometry = self.root.geometry()
            self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
            self._maximized = True
        self._update_controls()

    def _update_controls(self):
        if "maximize" in self.controls:
            self.controls["maximize"].configure(text="❐" if self.maximized() else "□")

    def _start_move(self, event):
        self._drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _move(self, event):
        if not self._drag:
            return
        if self.native:
            self._drag = None
            self.native.drag(HTCAPTION, event.x_root, event.y_root)
        elif not self._maximized:
            px, py, x, y = self._drag
            self.root.geometry(f"+{x + event.x_root - px}+{y + event.y_root - py}")

    def _double_click(self, event):
        self._drag = None
        self.toggle_maximize()
        return "break"

    def _resize_handles(self):
        handles = [(HTLEFT, "sb_h_double_arrow", {"x": 0, "y": 7, "width": 5, "relheight": 1, "height": -14}), (HTRIGHT, "sb_h_double_arrow", {"relx": 1, "x": -5, "y": 7, "width": 5, "relheight": 1, "height": -14}), (HTTOP, "sb_v_double_arrow", {"x": 7, "y": 0, "height": 5, "relwidth": 1, "width": -14}), (HTBOTTOM, "sb_v_double_arrow", {"x": 7, "rely": 1, "y": -5, "height": 5, "relwidth": 1, "width": -14}), (HTTOPLEFT, "top_left_corner", {"x": 0, "y": 0, "width": 7, "height": 7}), (HTTOPRIGHT, "top_right_corner", {"relx": 1, "x": -7, "y": 0, "width": 7, "height": 7}), (HTBOTTOMLEFT, "bottom_left_corner", {"x": 0, "rely": 1, "y": -7, "width": 7, "height": 7}), (HTBOTTOMRIGHT, "bottom_right_corner", {"relx": 1, "x": -7, "rely": 1, "y": -7, "width": 7, "height": 7})]
        self.handles = []
        for edge, cursor, position in handles:
            if os.name == "nt":
                cursor = "size_we" if edge in (HTLEFT, HTRIGHT) else "size_ns" if edge in (HTTOP, HTBOTTOM) else "size_nw_se" if edge in (HTTOPLEFT, HTBOTTOMRIGHT) else "size_ne_sw"
            handle = tk.Frame(self.root, background=theme.BG, cursor=cursor)
            handle.place(**position)
            handle.bind("<ButtonPress-1>", lambda event, h=edge: self._resize_start(event, h))
            handle.bind("<B1-Motion>", self._resize_move)
            self.handles.append(handle)

    def _resize_start(self, event, edge):
        if self.maximized():
            return
        if self.native:
            self.native.drag(edge, event.x_root, event.y_root)
        else:
            self._sizing = (edge, event.x_root, event.y_root, (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height()))

    def _resize_move(self, event):
        if self.native or not getattr(self, "_sizing", None) or self.maximized():
            return
        edge, px, py, start = self._sizing
        x, y, width, height = resized(start, edge, event.x_root - px, event.y_root - py, self.root.minsize())
        self.root.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def _configured(self, event):
        if event.widget == self.root:
            self._update_controls()

    def _mapped(self, event):
        if event.widget == self.root and self._fallback_minimized:
            self._fallback_minimized = False
            self.root.after_idle(lambda: self.root.overrideredirect(True))

    def _destroyed(self, event):
        if event.widget == self.root and self.native:
            self.native.close()
