import ctypes
import os
from types import SimpleNamespace
import unittest

from enge_spx.window_frame import (
    HTCLIENT, HTLEFT, HTRIGHT, HTTOP, HTBOTTOM,
    HTTOPLEFT, HTTOPRIGHT, HTBOTTOMLEFT, HTBOTTOMRIGHT,
    MinMaxInfo, MonitorInfo, Point, Rect, edge_hit, resized,
)


class WindowGeometryTests(unittest.TestCase):
    def test_edges_and_corners_support_eight_resize_directions(self):
        for x, y, expected in [(1, 1, HTTOPLEFT), (998, 1, HTTOPRIGHT), (1, 698, HTBOTTOMLEFT), (998, 698, HTBOTTOMRIGHT), (500, 1, HTTOP), (500, 698, HTBOTTOM), (1, 350, HTLEFT), (998, 350, HTRIGHT), (500, 350, HTCLIENT)]:
            with self.subTest(x=x, y=y):
                self.assertEqual(edge_hit(x, y, 1000, 700), expected)

    def test_maximized_dialogs_and_outside_points_cannot_resize(self):
        self.assertEqual(edge_hit(1, 1, 1000, 700, maximized=True), HTCLIENT)
        self.assertEqual(edge_hit(1, 1, 1000, 700, resizable=False), HTCLIENT)
        self.assertEqual(edge_hit(-1, 1, 1000, 700), HTCLIENT)

    def test_left_top_resize_keeps_opposite_edge_and_minimum(self):
        start = (-900, 100, 800, 600)
        self.assertEqual(resized(start, HTTOPLEFT, 1000, 1000, (500, 400)), (-600, 300, 500, 400))
        self.assertEqual(resized(start, HTTOPLEFT, -50, -50, (500, 400)), (-950, 50, 850, 650))

    def test_right_bottom_resize_never_moves_the_origin(self):
        self.assertEqual(resized((100, 200, 800, 600), HTBOTTOMRIGHT, -900, -900, (500, 400)), (100, 200, 500, 400))
        self.assertEqual(resized((100, 200, 800, 600), HTRIGHT, 100, 300, (500, 400)), (100, 200, 900, 600))

    def test_native_structures_use_fixed_width_windows_fields(self):
        self.assertEqual(ctypes.sizeof(Rect), 16)
        self.assertEqual(ctypes.sizeof(MinMaxInfo), 40)
        self.assertEqual(ctypes.sizeof(MonitorInfo), 40)


@unittest.skipUnless(os.name == "nt", "Native Windows custom-frame checks")
class NativeFrameTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from enge_spx import theme
        from enge_spx.platform_ui import prepare_windows
        from enge_spx.window_frame import WindowFrame
        prepare_windows()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.root.geometry("720x500+40+40")
        self.root.minsize(420, 300)
        theme.apply(self.root)
        self.root.update_idletasks()
        user = ctypes.WinDLL("user32")
        user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user.GetAncestor.restype = ctypes.c_void_p
        user.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.window_proc = user.GetWindowLongPtrW(user.GetAncestor(self.root.winfo_id(), 2), -4)
        self.frame = WindowFrame(self.root)
        tk.Label(self.frame.content, text="ENGE SPX native frame", bg=theme.BG, fg=theme.ACCENT).pack(pady=30)
        self.root.deiconify()
        self.root.update()
        self.native = self.frame.native
        self.assertIsNotNone(self.native, "Windows must use the native frame backend")
        self.assertTrue(self.native.active)

    def test_full_client_area_has_no_system_caption_and_retains_shell_styles(self):
        outer, client = Rect(), Rect()
        self.native.user.GetWindowRect(self.native.hwnd, ctypes.byref(outer))
        self.native.user.GetClientRect(self.native.hwnd, ctypes.byref(client))
        self.assertLessEqual(abs((outer.right - outer.left) - client.right), 2)
        self.assertLessEqual(abs((outer.bottom - outer.top) - client.bottom), 2)
        style = self.native.user.GetWindowLongPtrW(self.native.hwnd, -16)
        self.assertEqual(style & 0x00C40000, 0)  # no caption or system sizing frame
        self.assertEqual(style & 0x00030000, 0x00030000)  # native minimize/maximize state
        extended = self.native.user.GetWindowLongPtrW(self.native.hwnd, -20)
        self.assertTrue(extended & 0x00040000)
        self.assertFalse(extended & 0x00000080)
        area = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        self.native.user.GetMonitorInfoW(self.native.user.MonitorFromWindow(self.native.hwnd, 2), ctypes.byref(area))
        self.assertGreaterEqual(outer.top, area.work.top)
        self.assertLessEqual(outer.bottom, area.work.bottom)

    def test_minimize_maximize_and_restore_use_native_window_state(self):
        self.frame.minimize()
        self.root.update()
        self.assertTrue(self.native.user.IsIconic(self.native.hwnd))
        self.frame.restore()
        self.root.update()
        self.assertFalse(self.native.user.IsIconic(self.native.hwnd))
        self.frame.toggle_maximize()
        self.root.update()
        self.assertTrue(self.frame.maximized())
        area = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        self.native.user.GetMonitorInfoW(self.native.user.MonitorFromWindow(self.native.hwnd, 2), ctypes.byref(area))
        client, origin = Rect(), Point()
        self.native.user.GetClientRect(self.native.hwnd, ctypes.byref(client))
        self.native.user.ClientToScreen(self.native.hwnd, ctypes.byref(origin))
        # Native invisible resize margins may sit outside the monitor. The
        # visible client area and its custom title bar must stay inside it.
        self.assertGreaterEqual(origin.y, area.work.top - 2)
        self.assertGreaterEqual(origin.x, area.work.left - 2)
        self.assertLessEqual(origin.y + client.bottom, area.work.bottom + 2)
        self.assertLessEqual(origin.x + client.right, area.work.right + 2)
        self.frame.restore()
        self.root.update()
        self.assertFalse(self.frame.maximized())

    def test_tk_window_procedure_remains_installed(self):
        self.assertEqual(self.native.user.GetWindowLongPtrW(self.native.hwnd, -4), self.window_proc)

    def test_custom_handles_resize_without_a_native_callback(self):
        self.assertEqual(len(self.frame.handles), 8)
        width, height = self.root.winfo_width(), self.root.winfo_height()
        self.frame._resize_start(SimpleNamespace(x_root=200, y_root=200), HTBOTTOMRIGHT)
        self.frame._resize_move(SimpleNamespace(x_root=270, y_root=240))
        self.root.update()
        self.assertEqual(self.root.winfo_width(), width + 70)
        self.assertEqual(self.root.winfo_height(), height + 40)
        self.frame._resize_start(SimpleNamespace(x_root=200, y_root=200), HTTOPLEFT)
        self.frame._resize_move(SimpleNamespace(x_root=2200, y_root=2200))
        self.root.update()
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), self.root.minsize())


if __name__ == "__main__":
    unittest.main()
