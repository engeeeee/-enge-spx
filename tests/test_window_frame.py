import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from enge_spx.state import Store
from enge_spx.ui import style
from enge_spx.ui.controller import Controller, Value
from enge_spx.ui.window import Window


class NativeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        style.apply(cls.app)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.controller = Controller(Store(Path(self.folder.name)))
        self.window = Window(self.controller)
        self.window.show()
        QTest.qWait(50)
        self.addCleanup(self.window.finish_close)

    def test_native_frameless_window_keeps_complete_branding(self):
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.window.titlebar.controls["close"].isVisible())
        if self.window.compact:
            self.assertIn("ENGE SPX", self.window.titlebar.caption.text())
        else:
            self.assertGreaterEqual(self.window.brand_label.width(), self.window.brand_label.sizeHint().width())
        self.assertEqual(len(self.window.resize_edges), 8)

    def test_reveal_recovers_hidden_and_minimized_windows(self):
        self.window.hide()
        QTest.qWait(20)
        self.assertFalse(self.window.isVisible())
        self.window.reveal()
        QTest.qWait(30)
        self.assertTrue(self.window.isVisible())
        self.window.minimize()
        QTest.qWait(30)
        self.assertTrue(self.window.isMinimized())
        self.window.reveal()
        QTest.qWait(30)
        self.assertFalse(self.window.isMinimized())

    def test_desktop_readiness_reveals_only_when_not_minimized_by_user(self):
        self.window.hide()
        self.controller.update_stage({"stage": "docker_start"})
        self.controller.update_stage({"stage": "docker_ready"})
        QTest.qWait(30)
        self.assertTrue(self.window.isVisible())
        self.window.minimize()
        self.controller.update_stage({"stage": "docker_start"})
        self.controller.update_stage({"stage": "docker_ready"})
        QTest.qWait(30)
        self.assertTrue(self.window.isMinimized())

    def test_idle_state_does_not_rewrite_widgets(self):
        count = self.window.render_count
        QTest.qWait(1550)
        self.assertEqual(self.window.render_count, count)
        self.assertFalse(self.controller.delivery.isActive())

    def test_small_width_uses_compact_sidebar_without_cropping_the_name(self):
        self.window.resize(810, 620)
        QTest.qWait(40)
        self.assertTrue(self.window.compact)
        self.assertIn("ENGE SPX", self.window.titlebar.caption.text())
        self.assertTrue(self.window.next_button.isVisible())
        self.window.resize(1200, 820)
        QTest.qWait(40)
        self.assertFalse(self.window.compact)
        self.assertTrue(self.window.brand_label.isVisible())
        self.assertGreaterEqual(self.window.brand_label.width(), self.window.brand_label.sizeHint().width())

    def test_value_emits_only_real_changes(self):
        value = Value("before")
        spy = QSignalSpy(value.changed)
        value.set("before")
        value.set("after")
        value.set("after")
        self.assertEqual(spy.count(), 1)

    def test_close_hides_to_tray_without_canceling_work_or_stopping_monitor_timers(self):
        with patch("enge_spx.ui.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            self.assertTrue(self.window.install_tray())
            self.controller.busy = True
            with patch.object(self.controller, "request_close") as close:
                self.window.close()
                QTest.qWait(20)
                self.assertFalse(self.window.isVisible())
                self.assertTrue(self.window.tray.isVisible())
                self.assertFalse(self.controller.cancel.is_set())
                self.assertTrue(self.controller.status_timer.isActive())
                close.assert_not_called()
            self.window.return_from_desktop()
            self.assertFalse(self.window.isVisible())
            self.window.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
            self.assertTrue(self.window.isVisible())
            self.controller.busy = False

    def test_tray_exit_closes_interface_and_stop_exit_stops_only_the_workspace(self):
        with patch("enge_spx.ui.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            self.window.install_tray()
            with patch.object(self.controller, "run") as run:
                self.window.stop_and_exit()
                run.assert_called_once()
                engine = Mock()
                run.call_args.args[0](engine)
                engine.stop.assert_called_once_with()
            closed = QSignalSpy(self.window.closed)
            self.window.tray_exit.trigger()
            QTest.qWait(20)
            self.assertEqual(closed.count(), 1)
            self.assertFalse(self.window.tray.isVisible())

    def test_no_tray_keeps_normal_exit_and_never_hides_an_unreachable_background_app(self):
        with patch("enge_spx.ui.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
            self.assertFalse(self.window.install_tray())
            closed = QSignalSpy(self.window.closed)
            self.window.close()
            self.assertEqual(closed.count(), 1)

    def test_legacy_terminal_reopens_as_custom_and_exe_picker_has_no_brand_special_case(self):
        store = Store(Path(self.folder.name) / "legacy-terminal")
        store.write("settings.json", {**store.settings(), "terminal": {"kind": "pebrel", "executable": "D:/Terminals/pebrel.exe"}})
        controller = Controller(store)
        window = Window(controller)
        self.addCleanup(window.finish_close)
        self.assertEqual(controller.terminal_kind.get(), "custom")
        self.assertEqual(controller.terminal_exe.get(), "D:/Terminals/pebrel.exe")
        self.assertIn("{command}", controller.terminal_args.get())
        for name in ("pebrel.exe", "another-terminal.exe"):
            controller.terminal_kind.set("auto")
            with patch("enge_spx.ui.window.QFileDialog.getOpenFileName", return_value=("D:/Terminals/" + name, "")):
                window.choose_terminal()
            self.assertEqual(controller.terminal_kind.get(), "custom")
            self.assertEqual(controller.terminal_exe.get(), "D:/Terminals/" + name)


if __name__ == "__main__":
    unittest.main()
