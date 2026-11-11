import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication
from enge_spx.state import Store, SPXError
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window


class MeasurementUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.c = Controller(Store(self.root / "data"))
        self.w = Window(self.c)
        self.w.show()
        self.c.notify = Mock()
        self.addCleanup(self.w.finish_close)
        self.engine = Mock()
        self.engine.network_performance.return_value = {"schema": 1, "kind": "network_performance", "status": "checked", "measurement": {"cold_https_first_byte_ms": {"median": 100}, "download": {"request_mbps": 5.0}}}
        self.engine.shutdown.return_value = {"workspace_stopped": True, "background_stopped": True}
        self.factory = patch("enge_spx.ui.controller.Engine", return_value=self.engine)
        self.factory.start(); self.addCleanup(self.factory.stop)

    def spin(self, condition):
        until = time.monotonic() + 3
        while not condition() and time.monotonic() < until:
            QTest.qWait(15); time.sleep(.005)
        self.assertTrue(condition())

    def test_page_is_lazy_and_does_not_measure_on_open(self):
        self.assertNotIn("network", self.w.pages)
        self.w.show_page("network")
        self.assertFalse(self.w.network_measure_button.isEnabled())
        self.assertFalse(self.w.network_measure_export_button.isEnabled())
        self.assertIsNone(self.c.network_performance_report)
        self.engine.network_performance.assert_not_called()

    def test_button_runs_once_and_export_only_saves_cached_evidence(self):
        self.w.show_page("network")
        self.c.view["ready"] = True
        self.w.update_network_measurement_controls()
        self.w.network_measure_button.click()
        self.spin(lambda: not self.c.busy)
        self.engine.network_performance.assert_called_once()
        self.assertTrue(self.w.network_measure_export_button.isEnabled())
        self.assertIn("100.0 ms", self.c.network_performance_summary.get())
        self.assertIn("5.00 Mbps", self.c.network_performance_summary.get())
        output = self.root / "saved.json"
        self.c.export_network_performance(output)
        self.spin(lambda: not self.c.busy)
        self.assertEqual(json.loads(output.read_text()), self.c.network_performance_report)
        self.engine.network_performance.assert_called_once()

    def test_new_failure_does_not_export_previous_measurement_as_current(self):
        self.c.network_performance_report = {"old": True}
        self.c.network_performance_available.set(True)
        self.engine.network_performance.side_effect = SPXError("测量操作不可用")
        self.c.check_network_performance()
        self.spin(lambda: not self.c.busy)
        self.assertIsNone(self.c.network_performance_report)
        self.assertFalse(self.c.network_performance_available.get())
        self.assertFalse(self.c.export_network_performance(self.root / "stale.json"))
        self.assertFalse((self.root / "stale.json").exists())

    def test_genuine_exit_waits_for_measurement_before_shutdown_without_followup_report(self):
        entered, release = threading.Event(), threading.Event()
        closed = QSignalSpy(self.c.close_requested)
        def measure():
            entered.set(); release.wait(2)
            return {"status": "checked"}
        self.engine.network_performance.side_effect = measure
        try:
            self.c.check_network_performance()
            self.assertTrue(entered.wait(1))
            self.assertFalse(self.c.check_network_performance())
            self.c.request_exit()
            self.assertEqual(self.c.exit_stage, "waiting")
            self.engine.shutdown.assert_not_called()
            release.set()
            self.spin(lambda: closed.count() == 1)
            self.engine.shutdown.assert_called_once()
            self.assertIsNone(self.c.network_performance_report)
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
