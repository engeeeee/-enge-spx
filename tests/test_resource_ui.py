import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from enge_spx.state import Store
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window


class ResourceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.controller = Controller(self.store)
        self.window = Window(self.controller)
        self.window.show()
        self.addCleanup(self.window.finish_close)

    def test_preset_values_and_browser_switch_are_not_persisted_until_saved(self):
        controller = self.controller
        self.window.show_page("resources")
        controller.resource_mode.set("low")
        self.assertEqual(controller.budget_project_memory.get(), 2048)
        self.assertEqual(controller.budget_project_cpu.get(), 1)
        self.assertFalse(controller.auto_browser.get())
        self.assertNotIn("resources", self.store.settings())
        controller.budget_project_memory.set(3072)
        self.assertEqual(controller.resource_mode.get(), "custom")

    def test_sampling_never_overlaps_or_changes_operation_busy_and_hides_cleanly(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def sample(engine, ready):
            calls.append(ready)
            entered.set()
            release.wait(3)
            return None
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=sample):
            try:
                self.window.show_page("resources")
                self.assertTrue(entered.wait(2))
                self.controller.sample_resources()
                self.controller.sample_resources()
                QTest.qWait(80)
                self.assertEqual(calls, [False])
                self.assertFalse(self.controller.busy)
                self.assertTrue(self.controller.delivery.isActive())
                caption = self.controller.resource_caption.get()
                self.window.hide()
                self.assertFalse(self.controller.resource_timer.isActive())
                self.assertTrue(self.controller.status_timer.isActive())
                self.assertEqual(self.controller.status_timer.interval(), 10000)
                release.set()
                deadline = time.monotonic() + 2
                while self.controller.resource_inflight and time.monotonic() < deadline:
                    QTest.qWait(20)
                self.assertFalse(self.controller.resource_inflight)
                self.assertEqual(self.controller.resource_caption.get(), caption)
                self.assertFalse(self.controller.delivery.isActive())
            finally:
                release.set()

    def test_navigation_minimize_and_real_exit_suspend_only_display_sampling(self):
        with patch.object(self.controller, "sample_resources"):
            self.window.show_page("resources")
            self.assertTrue(self.controller.resource_timer.isActive())
            self.window.show_page("overview")
            self.assertFalse(self.controller.resource_timer.isActive())
            self.window.show_page("resources")
            self.window.minimize()
            QTest.qWait(30)
            self.assertFalse(self.controller.resource_timer.isActive())
            self.window.reveal()
            self.assertTrue(self.controller.resource_timer.isActive())
            self.window.finish_close()
            self.assertTrue(self.controller.resource_closed)
            self.assertFalse(self.controller.resource_timer.isActive())
            self.assertFalse(self.controller.status_timer.isActive())


if __name__ == "__main__":
    unittest.main()
