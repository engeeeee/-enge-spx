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

from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from enge_spx.state import Store
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window
from test_resource_recording import evidence


class RecordingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.c = Controller(self.store)
        self.window = Window(self.c)
        self.window.show()
        self.output = self.root / "real-work.json"
        self.c.notify = Mock()
        self.addCleanup(self.cleanup_window)

    def spin(self, predicate, seconds=3):
        until = time.monotonic() + seconds
        while not predicate() and time.monotonic() < until:
            QTest.qWait(10)
            time.sleep(.005)  # Let real file I/O workers run on Python 3.12/Windows.
        self.assertTrue(predicate())

    def cleanup_window(self):
        self.c.stop_resource_recording()
        self.spin(lambda: not self.c.record_active.get())
        self.window.finish_close()
        self.spin(lambda: not self.c.resource_inflight)

    def show_without_automatic_query(self):
        with patch.object(self.c, "sample_resources"):
            self.window.show_page("resources")

    def test_first_click_queues_behind_existing_sample_and_cancel_starts_no_record(self):
        entered, release = threading.Event(), threading.Event()
        def sample(*args):
            entered.set()
            release.wait(3)
            return evidence()
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=sample):
            try:
                self.window.show_page("resources")
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.c.start_resource_recording(self.output))
                self.assertIsNotNone(self.c.record_pending)
                self.assertFalse(self.c.start_resource_recording(self.output))
                self.c.stop_resource_recording()
                release.set()
                self.spin(lambda: not self.c.resource_inflight)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.c.record_running)
                self.assertTrue(self.c.resource_timer.isActive())
            finally:
                release.set()

    def test_recording_and_live_queries_never_overlap_and_hidden_record_keeps_running(self):
        entered, release = threading.Event(), threading.Event()
        calls, active = [], [0]
        def sample(*args):
            active[0] += 1
            self.assertEqual(active[0], 1)
            calls.append(args[1])
            if len(calls) == 1:
                entered.set()
                release.wait(3)
            active[0] -= 1
            return evidence()
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=sample), patch("enge_spx.engine.Engine.ready", side_effect=AssertionError("Recording renewed/started a workspace")):
            try:
                self.window.show_page("resources")
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.c.start_resource_recording(self.output))
                release.set()
                self.spin(lambda: len(calls) == 2 and self.c.record_running)
                self.c.sample_resources()
                self.assertEqual(len(calls), 2)
                self.window.hide()
                self.assertTrue(self.c.record_active.get())
                self.assertFalse(self.c.record_cancel.is_set())
                self.assertFalse(self.c.resource_timer.isActive())
                self.assertFalse(self.c.busy)
                self.c.stop_resource_recording()
                self.spin(lambda: not self.c.record_active.get())
                result = json.loads(self.output.read_text())
                self.assertEqual(result["source"], "gui")
                self.assertEqual(result["end_reason"], "user_stop")
                self.assertEqual(result["sample_count"], 1)
                self.assertNotIn("private-", self.output.read_text())
            finally:
                release.set()

    def test_real_exit_waits_for_record_save_after_workspace_stop(self):
        self.show_without_automatic_query()
        entered, release = threading.Event(), threading.Event()
        closed = []
        self.c.close_requested.connect(lambda: closed.append(True))
        def sample(*args):
            entered.set()
            release.wait(3)
            return evidence()
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=sample), patch("enge_spx.engine.Engine.shutdown", return_value={"workspace_stopped": True, "background_stopped": True}) as shutdown:
            try:
                self.c.start_resource_recording(self.output)
                self.assertTrue(entered.wait(2))
                self.c.request_exit()
                self.spin(lambda: self.c.exit_stage == "finalizing")
                shutdown.assert_called_once()
                self.assertFalse(closed)
                release.set()
                self.spin(lambda: bool(closed))
                self.assertFalse(self.c.resource_inflight)
                self.assertEqual(json.loads(self.output.read_text())["end_reason"], "app_exit")
            finally:
                release.set()

    def test_data_migration_automatically_finishes_recording_and_uses_captured_target(self):
        self.show_without_automatic_query()
        with patch("enge_spx.resource_monitor.Monitor.snapshot", return_value=evidence()), patch.object(self.c, "_migrate_data") as migrate:
            self.c.start_resource_recording(self.output)
            self.spin(lambda: "份采样" in self.c.record_status.get())
            self.c.data_target.set(str(self.root / "chosen"))
            self.c.migrate_data()
            self.c.data_target.set(str(self.root / "later-edit"))
            self.spin(lambda: migrate.called)
            migrate.assert_called_once_with(str(self.root / "chosen"))
            self.assertEqual(json.loads(self.output.read_text())["end_reason"], "storage_change")
            self.assertFalse(self.c.resource_inflight)

    def test_optional_desktop_shutdown_runs_only_after_real_record_file_is_saved(self):
        self.show_without_automatic_query()
        self.c.desktop_exit_supported = self.c.saved_close_desktop = True
        entered, release = threading.Event(), threading.Event()
        def sample(*args):
            entered.set(); release.wait(3)
            return evidence()
        def stop(docker, progress):
            self.assertFalse(self.c.resource_inflight)
            self.assertEqual(json.loads(self.output.read_text())["end_reason"], "app_exit")
            self.assertFalse(list(self.root.glob("*.partial")))
            return {"docker_desktop_stopped": True}
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=sample), patch("enge_spx.engine.Engine.shutdown", return_value={"workspace_stopped": True, "background_stopped": True}), patch("enge_spx.ui.controller.stop_desktop", side_effect=stop) as close:
            try:
                self.c.start_resource_recording(self.output)
                self.assertTrue(entered.wait(2))
                self.c.request_exit()
                self.spin(lambda: self.c.exit_stage == "finalizing")
                close.assert_not_called()
                release.set()
                self.spin(lambda: self.c.exit_desktop_done)
                close.assert_called_once()
            finally:
                release.set()

    def test_save_failure_keeps_record_for_export_without_new_sampling(self):
        self.show_without_automatic_query()
        with patch("enge_spx.resource_monitor.Monitor.snapshot", return_value=evidence()), patch("enge_spx.resource_recording.atomic_json", side_effect=PermissionError("private-path")):
            self.c.start_resource_recording(self.output)
            self.spin(lambda: "份采样" in self.c.record_status.get())
            self.c.stop_resource_recording()
            self.spin(lambda: not self.c.record_active.get())
        self.assertTrue(self.c.record_available.get())
        self.assertNotIn("private-path", str(self.c.notify.call_args))
        exported = self.root / "retry.json"
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=AssertionError("Export resampled")):
            self.c.export_resource_recording(exported)
            self.spin(lambda: not self.c.busy)
        self.assertEqual(json.loads(exported.read_text()), self.c.last_record_report)

    def test_record_tab_buttons_need_explicit_output_and_keep_stop_enabled_during_work(self):
        self.show_without_automatic_query()
        self.window.select_resource_view("record")
        self.assertFalse(self.c.resource_timer.isActive())
        with patch("enge_spx.ui.window.QFileDialog.getSaveFileName", return_value=("", "")):
            QTest.mouseClick(self.window.record_start, Qt.MouseButton.LeftButton)
        self.assertFalse(self.c.record_active.get())
        with patch("enge_spx.resource_monitor.Monitor.snapshot", return_value=evidence()), patch("enge_spx.ui.window.QFileDialog.getSaveFileName", return_value=(str(self.output), "JSON")):
            QTest.mouseClick(self.window.record_start, Qt.MouseButton.LeftButton)
            self.spin(lambda: "份采样" in self.c.record_status.get())
            self.assertFalse(self.window.record_start.isEnabled())
            self.c.busy = True
            self.c.refresh()
            self.assertTrue(self.window.record_stop.isEnabled())
            QTest.mouseClick(self.window.record_stop, Qt.MouseButton.LeftButton)
            self.spin(lambda: not self.c.record_active.get())
            self.c.busy = False
            self.c.refresh()
        self.assertTrue(self.window.record_export.isEnabled())

    def test_output_chosen_while_operation_finishes_queues_instead_of_losing_first_click(self):
        self.show_without_automatic_query()
        self.c.busy = True
        with patch("enge_spx.resource_monitor.Monitor.snapshot", return_value=evidence()):
            self.assertTrue(self.c.start_resource_recording(self.output))
            self.assertIsNotNone(self.c.record_pending)
            self.assertFalse(self.output.exists())
            self.c.busy = False
            self.spin(lambda: self.c.record_running and "份采样" in self.c.record_status.get())
            self.c.stop_resource_recording()
            self.spin(lambda: not self.c.record_active.get())
        self.assertEqual(json.loads(self.output.read_text())["sample_count"], 1)

    def test_failed_new_record_does_not_export_previous_record_as_current_data(self):
        self.show_without_automatic_query()
        self.c.last_record_report = {"schema": 1, "previous": True}
        self.c.record_available.set(True)
        with patch("enge_spx.resource_recording.record", side_effect=RuntimeError("private-error")):
            self.c.start_resource_recording(self.output)
            self.spin(lambda: not self.c.record_active.get())
        self.assertIsNone(self.c.last_record_report)
        self.assertFalse(self.c.record_available.get())
        self.assertNotIn("private-error", str(self.c.notify.call_args))


if __name__ == "__main__":
    unittest.main()
