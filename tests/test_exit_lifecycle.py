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
from enge_spx.downloads import DownloadPaused
from enge_spx.engine import Engine
from enge_spx.state import Store, SPXError
from enge_spx.ui.controller import Controller


class ExitLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name) / "data")
        self.controller = Controller(self.store)
        self.closed = QSignalSpy(self.controller.close_requested)
        self.fake_engine = Mock()
        self.fake_engine.shutdown.return_value = {"workspace_stopped": True, "background_stopped": True}
        self.factory = patch("enge_spx.ui.controller.Engine", return_value=self.fake_engine)
        self.make_engine = self.factory.start()
        self.addCleanup(self.factory.stop)
        def cleanup():
            self.controller.stop_resource_monitor()
            self.controller.delivery.stop()
            self.controller.status_timer.stop()
            self.controller.refresh_timer.stop()
        self.addCleanup(cleanup)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(predicate(), "Exit transition did not complete")

    def test_default_exit_stops_once_and_rejects_new_work_until_closed(self):
        c = self.controller
        self.assertTrue(c.request_exit())
        self.assertFalse(c.request_exit())
        self.assertFalse(c.run(lambda engine: None))
        self.wait_for(lambda: self.closed.count() == 1)
        self.fake_engine.shutdown.assert_called_once_with()
        self.assertEqual(c.exit_stage, "closing")

    def test_cancelable_operation_is_safely_paused_before_shutdown(self):
        c = self.controller
        entered = threading.Event()
        done = Mock()
        def download(engine):
            entered.set()
            if not c.cancel.wait(2):
                raise AssertionError("Exit did not cancel preparation")
            raise DownloadPaused("fixture download paused")
        c.run(download, done, cancelable=True)
        self.assertTrue(entered.wait(1))
        c.request_exit()
        self.assertTrue(c.cancel.is_set())
        self.wait_for(lambda: self.closed.count() == 1)
        done.assert_not_called()
        self.fake_engine.shutdown.assert_called_once()

    def test_non_cancelable_operation_finishes_without_followup_dialog_or_launch(self):
        c = self.controller
        entered, release = threading.Event(), threading.Event()
        def operation(engine):
            entered.set()
            release.wait(2)
            return "finished"
        done = Mock(side_effect=AssertionError("An exit must not open a review dialog"))
        try:
            c.run(operation, done)
            self.assertTrue(entered.wait(1))
            c.request_exit()
            self.assertEqual(c.exit_stage, "waiting")
            self.assertFalse(c.cancel.is_set())
            self.fake_engine.shutdown.assert_not_called()
            release.set()
            self.wait_for(lambda: self.closed.count() == 1)
            done.assert_not_called()
            self.fake_engine.shutdown.assert_called_once()
        finally:
            release.set()

    def test_relocation_bookkeeping_is_preserved_before_exit_uses_new_store(self):
        c = self.controller
        entered, release = threading.Event(), threading.Event()
        replacement = Store(Path(self.folder.name) / "moved")
        def operation(engine):
            entered.set(); release.wait(2)
            return replacement
        try:
            c.run(operation, lambda store: setattr(c, "store", store), done_on_exit=True)
            self.assertTrue(entered.wait(1))
            c.request_exit()
            release.set()
            self.wait_for(lambda: self.closed.count() == 1)
            self.assertIs(self.make_engine.call_args.args[0], replacement)
        finally:
            release.set()

    def test_keep_exit_requires_explicit_consent_and_never_stops_workspace(self):
        c = self.controller
        c.ask = Mock(return_value=False)
        self.assertFalse(c.request_exit("keep"))
        self.assertIsNone(c.exit_mode)
        self.assertEqual(self.closed.count(), 0)
        c.ask.return_value = True
        self.assertTrue(c.request_exit("keep"))
        self.assertEqual(self.closed.count(), 1)
        self.fake_engine.shutdown.assert_not_called()

    def test_failed_shutdown_keeps_interface_open_and_supports_retry(self):
        c = self.controller
        failed = QSignalSpy(c.exit_failed)
        self.fake_engine.shutdown.side_effect = SPXError("fixture stop failure")
        c.request_exit()
        self.wait_for(lambda: failed.count() == 1)
        self.assertEqual(self.closed.count(), 0)
        self.assertIsNone(c.exit_mode)
        self.assertFalse(c.busy)
        self.assertEqual(c.exit_stage, "failed")
        self.fake_engine.shutdown.side_effect = None
        c.request_exit()
        self.wait_for(lambda: self.closed.count() == 1)
        self.assertEqual(self.fake_engine.shutdown.call_count, 2)

    def test_exit_uses_last_verified_context_if_editing_settings_broke_engine_creation(self):
        self.store.write("controller-context.json", {"instance": self.store.instance, "context": "desktop-linux"})
        self.make_engine.side_effect = [SPXError("invalid edited settings"), self.fake_engine]
        with patch("enge_spx.docker_env.require_local_context", return_value="npipe:////./pipe/dockerDesktopLinuxEngine") as local:
            self.controller.request_exit()
            self.wait_for(lambda: self.closed.count() == 1)
        local.assert_called_once_with(self.fake_engine.docker)
        self.assertEqual(self.make_engine.call_args.kwargs["stop_context"], "desktop-linux")
        self.fake_engine.doctor.assert_not_called()
        self.fake_engine.shutdown.assert_called_once()

    def test_incomplete_stop_result_is_failure_and_does_not_close(self):
        self.fake_engine.shutdown.return_value = {"workspace_stopped": False}
        self.controller.request_exit()
        self.wait_for(lambda: self.controller.exit_stage == "failed")
        self.assertEqual(self.closed.count(), 0)

    def test_exit_cancels_and_waits_for_inflight_resource_sample(self):
        c = self.controller
        entered, release = threading.Event(), threading.Event()
        def sample(engine, ready, cancel):
            entered.set()
            release.wait(2)
            self.assertTrue(cancel.is_set())
            return None
        with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=sample):
            try:
                c.set_resource_visible(True)
                self.assertTrue(entered.wait(1))
                c.request_exit()
                self.wait_for(lambda: c.exit_stage == "finalizing")
                self.assertEqual(self.closed.count(), 0)
                self.assertFalse(c.resource_timer.isActive())
                release.set()
                self.wait_for(lambda: self.closed.count() == 1)
                self.assertFalse(c.resource_inflight)
            finally:
                release.set()

    def test_unsaved_checkbox_and_default_exit_do_not_close_desktop(self):
        c = self.controller
        c.desktop_exit_supported = True
        c.close_docker_desktop.set(True)
        with patch("enge_spx.ui.controller.stop_desktop") as stop:
            c.request_exit()
            self.wait_for(lambda: self.closed.count() == 1)
            stop.assert_not_called()

    def test_preference_save_is_independent_and_pending_exit_observes_saved_choice(self):
        c = self.controller
        c.desktop_exit_supported = True
        c.close_docker_desktop.set(True)
        entered, release = threading.Event(), threading.Event()
        from enge_spx.desktop_shutdown import save_preference
        def save(store, value):
            entered.set(); release.wait(2)
            return save_preference(store, value)
        def stopped(docker, progress):
            self.fake_engine.shutdown.assert_called_once()
            self.assertTrue(c.exit_workspace_stopped)
            self.assertFalse(c.resource_inflight)
            self.assertEqual(self.closed.count(), 0)
            return {"docker_desktop_stopped": True}
        with patch("enge_spx.ui.controller.save_exit_preference", side_effect=save), patch("enge_spx.ui.controller.stop_desktop", side_effect=stopped) as stop:
            try:
                c.save_exit_preferences()
                self.assertTrue(entered.wait(1))
                self.make_engine.assert_not_called()
                c.request_exit()
                self.assertEqual(c.exit_stage, "waiting")
                release.set()
                self.wait_for(lambda: self.closed.count() == 1)
                self.assertTrue(c.saved_close_desktop)
                self.assertTrue(c.exit_desktop_done)
                stop.assert_called_once()
            finally:
                release.set()

    def test_desktop_failure_preserves_stopped_workspace_and_can_retry(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        failed = QSignalSpy(c.exit_failed)
        with patch("enge_spx.ui.controller.stop_desktop", side_effect=[SPXError("fixture normal stop failed"), {"docker_desktop_stopped": True}]) as stop:
            c.request_exit()
            self.wait_for(lambda: failed.count() == 1)
            self.assertTrue(c.exit_workspace_stopped)
            self.assertIsNone(c.exit_mode)
            self.assertFalse(c.busy)
            self.assertEqual(self.closed.count(), 0)
            c.request_exit()
            self.wait_for(lambda: self.closed.count() == 1)
            self.assertEqual(stop.call_count, 2)
            self.fake_engine.shutdown.assert_called_once()

    def test_disabling_joint_exit_after_failed_confirmation_never_needs_docker_restart(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        with patch("enge_spx.ui.controller.stop_desktop", side_effect=SPXError("fixture confirmation failed")) as stop:
            c.request_exit()
            self.wait_for(lambda: c.exit_stage == "failed")
            c.close_docker_desktop.set(False)
            c.save_exit_preferences()
            self.wait_for(lambda: not c.busy)
            self.make_engine.side_effect = AssertionError("Retry constructed Engine for an already verified stopped workspace")
            c.request_exit()
            self.wait_for(lambda: self.closed.count() == 1)
            stop.assert_called_once()
            self.fake_engine.shutdown.assert_called_once()

    def test_one_time_app_exit_preserves_saved_choice_and_verified_stop(self):
        from enge_spx.desktop_shutdown import PREFERENCES, save_preference
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        c.close_docker_desktop.set(True)
        save_preference(self.store, True)
        preference = (self.store.home / PREFERENCES).read_bytes()
        self.store.write("runtime.json", {"phase": "stopped"})
        with patch("enge_spx.ui.controller.stop_desktop", side_effect=SPXError("fixture timeout")) as stop:
            c.request_exit()
            self.wait_for(lambda: c.exit_stage == "failed")
            self.make_engine.side_effect = AssertionError("Verified workspace must not need Docker again")
            self.assertTrue(c.exit_without_desktop_once())
            self.wait_for(lambda: self.closed.count() == 1)
            stop.assert_called_once()
            self.fake_engine.shutdown.assert_called_once()
        self.assertTrue(c.saved_close_desktop)
        self.assertTrue(c.close_docker_desktop.get())
        self.assertFalse(c.exit_desktop_done)
        self.assertEqual((self.store.home / PREFERENCES).read_bytes(), preference)

    def test_app_only_recovery_rejects_unverified_or_changed_workspace(self):
        c = self.controller
        c.notify = Mock()
        c.exit_stage = "failed"
        self.assertFalse(c.exit_without_desktop_once())
        for state in ({"phase": "ready"}, {}, []):
            self.store.write("runtime.json", state)
            c.exit_workspace_stopped, c.exit_docker = True, self.fake_engine.docker
            self.assertFalse(c.exit_without_desktop_once())
            self.assertFalse(c.exit_workspace_stopped)
        c.exit_workspace_stopped, c.exit_docker = True, self.fake_engine.docker
        with patch.object(self.store, "read", side_effect=SPXError("unreadable")):
            self.assertFalse(c.exit_without_desktop_once())
        self.assertEqual(self.closed.count(), 0)
        self.fake_engine.shutdown.assert_not_called()

    def test_already_closed_desktop_result_skips_another_global_stop(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        self.fake_engine.shutdown.return_value["docker_desktop_stopped"] = True
        with patch("enge_spx.ui.controller.stop_desktop") as stop:
            c.request_exit()
            self.wait_for(lambda: self.closed.count() == 1)
            self.assertTrue(c.exit_desktop_done)
            stop.assert_not_called()

    def test_new_engine_operation_invalidates_old_shutdown_proof(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        with patch("enge_spx.ui.controller.stop_desktop", side_effect=[SPXError("fixture confirmation failed"), {"docker_desktop_stopped": True}]):
            c.request_exit()
            self.wait_for(lambda: c.exit_stage == "failed")
            c.run(lambda engine: None)
            self.wait_for(lambda: not c.busy)
            self.assertFalse(c.exit_workspace_stopped)
            c.request_exit()
            self.wait_for(lambda: self.closed.count() == 1)
            self.assertEqual(self.fake_engine.shutdown.call_count, 2)

    def test_keep_exit_ignores_saved_close_desktop_choice(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        c.ask = Mock(return_value=True)
        with patch("enge_spx.ui.controller.stop_desktop") as stop:
            c.request_exit("keep")
            self.assertEqual(self.closed.count(), 1)
            stop.assert_not_called()
            self.fake_engine.shutdown.assert_not_called()

    def test_desktop_close_waits_for_active_record_or_resource_sample(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        c.resource_inflight = True
        with patch("enge_spx.ui.controller.stop_desktop", return_value={"docker_desktop_stopped": True}) as stop:
            c.request_exit()
            self.wait_for(lambda: c.exit_stage == "finalizing")
            stop.assert_not_called()
            self.assertEqual(self.closed.count(), 0)
            c.resource_inflight = False
            c.finish_exit_when_quiet()
            self.wait_for(lambda: self.closed.count() == 1)
            stop.assert_called_once()

    def test_workspace_failure_prevents_any_desktop_shutdown(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        self.fake_engine.shutdown.side_effect = SPXError("fixture workspace not stopped")
        with patch("enge_spx.ui.controller.stop_desktop") as stop:
            c.request_exit()
            self.wait_for(lambda: c.exit_stage == "failed")
            stop.assert_not_called()
            self.assertFalse(c.exit_workspace_stopped)
            self.assertEqual(self.closed.count(), 0)

    def test_failed_preference_save_cancels_queued_exit_instead_of_using_old_global_choice(self):
        c = self.controller
        c.desktop_exit_supported = c.saved_close_desktop = True
        c.close_docker_desktop.set(False)
        entered, release = threading.Event(), threading.Event()
        def denied(store, value):
            entered.set(); release.wait(2)
            raise PermissionError("private-fixture-secret")
        with patch("enge_spx.ui.controller.save_exit_preference", side_effect=denied), patch("enge_spx.ui.controller.stop_desktop") as stop:
            try:
                c.save_exit_preferences()
                self.assertTrue(entered.wait(1))
                c.request_exit()
                release.set()
                self.wait_for(lambda: c.exit_stage == "failed")
                self.assertIsNone(c.exit_mode)
                self.assertEqual(self.closed.count(), 0)
                self.fake_engine.shutdown.assert_not_called()
                stop.assert_not_called()
            finally:
                release.set()


class EngineShutdownTests(unittest.TestCase):
    def fixture(self, folder):
        store = Store(Path(folder))
        store.write("images.json", {"gateway": "fixture"})
        store.write("runtime.json", {"phase": "ready"})
        for name in ("gateway/config.json", "relay.json", "browser-token.json"):
            store.write(name, {"private": "fixture"})
        (store.home / "account-sentinel").write_text("preserved")
        engine = Engine(store)
        engine.docker = Mock(executable="docker.exe", secret_env={"TOKEN": "fixture"})
        engine.managed = Mock(side_effect=SPXError("missing Desktop Linux pipe"))
        return store, engine

    def test_closed_desktop_completes_local_cleanup_and_waits_for_background(self):
        with tempfile.TemporaryDirectory() as folder:
            store, engine = self.fixture(folder)
            entered, release = threading.Event(), threading.Event()
            def service():
                with store.lock("guard"):
                    entered.set()
                    release.wait(2)
                    time.sleep(.08)
            thread = threading.Thread(target=service)
            thread.start()
            self.assertTrue(entered.wait(1))
            def proof(docker):
                release.set()
                return True
            try:
                with patch("enge_spx.desktop_shutdown.stopped_for_context", side_effect=proof) as stopped:
                    result = engine.shutdown()
                self.assertTrue(result["docker_desktop_stopped"])
                self.assertTrue(result["workspace_stopped"] and result["background_stopped"])
                self.assertFalse(result["docker_desktop_kept"])
                self.assertEqual(stopped.call_count, 2)
                engine.managed.assert_called_once()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(store.read("runtime.json")["phase"], "stopped")
                self.assertEqual(store.read("gateway/lease.json")["expires"], 0)
                self.assertTrue(store.read("guard-stop.json")["requested"])
                for name in ("gateway/config.json", "relay.json", "browser-token.json"):
                    self.assertFalse((store.home / name).exists())
                self.assertEqual(engine.docker.secret_env, {})
                self.assertEqual(store.read("images.json"), {"gateway": "fixture"})
                self.assertEqual((store.home / "account-sentinel").read_text(), "preserved")
            finally:
                release.set()
                thread.join(2)

    def test_missing_pipe_with_unknown_desktop_is_not_shutdown_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            store, engine = self.fixture(folder)
            with patch("enge_spx.desktop_shutdown.stopped_for_context", return_value=False):
                with self.assertRaisesRegex(SPXError, "missing Desktop"):
                    engine.shutdown()

    def test_desktop_restart_during_cleanup_prevents_offline_success(self):
        with tempfile.TemporaryDirectory() as folder:
            store, engine = self.fixture(folder)
            with patch("enge_spx.desktop_shutdown.stopped_for_context", side_effect=[True, False]):
                with self.assertRaisesRegex(SPXError, "状态已变化"):
                    engine.shutdown()

    def test_offline_cleanup_cannot_mask_persistent_data_permission_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            store, engine = self.fixture(folder)
            with patch.object(store, "write", side_effect=PermissionError("denied")), patch("enge_spx.desktop_shutdown.stopped_for_context", return_value=True):
                with self.assertRaises(PermissionError):
                    engine.shutdown()

    def test_desktop_closes_between_container_stop_and_final_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            store, engine = self.fixture(folder)
            engine.managed.side_effect = [[], SPXError("missing Desktop Linux pipe")]
            with patch("enge_spx.desktop_shutdown.stopped_for_context", return_value=True) as stopped:
                result = engine.shutdown()
            self.assertTrue(result["docker_desktop_stopped"])
            self.assertEqual(engine.managed.call_count, 2)
            stopped.assert_called_once_with(engine.docker)

    def test_missing_docker_cannot_claim_installed_workspace_was_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.write("images.json", {"gateway": "fixture"})
            engine = Engine(store)
            engine.docker = Mock(executable=None)
            with self.assertRaisesRegex(SPXError, "无法核验"):
                engine.shutdown()
            self.assertEqual(store.read("runtime.json")["phase"], "stopped")
            self.assertEqual(store.read("gateway/lease.json")["expires"], 0)
    def test_shutdown_waits_for_background_lock_without_quitting_desktop(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            engine = Engine(store)
            engine.docker = Mock(executable=None)
            entered, stop = threading.Event(), threading.Event()
            def guard():
                with store.lock("guard"):
                    entered.set(); stop.wait(2); time.sleep(.1)
            thread = threading.Thread(target=guard)
            thread.start()
            self.assertTrue(entered.wait(1))
            try:
                engine._stop = Mock(side_effect=stop.set)
                result = engine.shutdown()
                self.assertTrue(result["workspace_stopped"])
                self.assertTrue(result["background_stopped"])
                thread.join(1)
                self.assertFalse(thread.is_alive())
                engine.docker.run.assert_not_called()
            finally:
                stop.set(); thread.join(2)

    def test_shutdown_never_reports_success_with_a_running_owned_container(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.write("images.json", {"gateway": "fixture"})
            engine = Engine(store)
            engine._stop = Mock()
            engine.managed = Mock(return_value=["fixture"])
            engine.docker = Mock(executable="docker.exe")
            engine.docker.inspect.return_value = {"Config": {"Labels": {engine.owner: store.instance}}, "State": {"Running": True}}
            with self.assertRaisesRegex(SPXError, "运行容器"):
                engine.shutdown()


if __name__ == "__main__":
    unittest.main()
