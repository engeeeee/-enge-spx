import ctypes
import os
import unittest

from enge_spx.window_frame import (
    HTCLIENT, HTLEFT, HTRIGHT, HTTOP, HTBOTTOM,
    HTTOPLEFT, HTTOPRIGHT, HTBOTTOMLEFT, HTBOTTOMRIGHT,
    MinMaxInfo, MonitorInfo, Rect, edge_hit, resized,
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
        self.assertEqual(style & 0x00070000, 0x00070000)  # resize, minimize, maximize
        extended = self.native.user.GetWindowLongPtrW(self.native.hwnd, -20)
        self.assertTrue(extended & 0x00040000)
        self.assertFalse(extended & 0x00000080)

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
        rect = Rect()
        self.native.user.GetWindowRect(self.native.hwnd, ctypes.byref(rect))
        self.assertGreaterEqual(rect.top, area.work.top - 2)
        self.assertLessEqual(rect.bottom, area.work.bottom + 2)
        self.frame.restore()
        self.root.update()
        self.assertFalse(self.frame.maximized())

    def test_native_hit_test_returns_resize_edges(self):
        rect = Rect()
        self.native.user.GetWindowRect(self.native.hwnd, ctypes.byref(rect))
        for x, y, expected in [(rect.left + 1, rect.top + 1, HTTOPLEFT), (rect.right - 2, rect.bottom - 2, HTBOTTOMRIGHT)]:
            packed = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
            self.assertEqual(self.native.user.SendMessageW(self.native.hwnd, 0x0084, 0, packed), expected)


if __name__ == "__main__":
    unittest.main()
