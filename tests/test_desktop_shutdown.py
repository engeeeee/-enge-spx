import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from enge_spx import desktop_shutdown as desktop
from enge_spx.state import Store, SPXError


def result(state=None, code=0, output=None):
    return subprocess.CompletedProcess([], code, json.dumps({"Status": state}) if output is None else output, "private-fixture-secret")


class DesktopShutdownTests(unittest.TestCase):
    def setUp(self):
        self.docker = SimpleNamespace(executable="docker.exe", secret_env={"PRIVATE_SESSION": "never-pass-this"})

    def test_default_and_explicit_preferences_do_not_read_or_rewrite_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            for name in ("settings.json", "nodes.json", "runtime.json"):
                (store.home / name).write_text("invalid-private-file", encoding="utf-8")
            self.assertFalse(desktop.load_preference(store))
            self.assertFalse((store.home / desktop.PREFERENCES).exists())
            desktop.save_preference(store, True)
            self.assertTrue(desktop.load_preference(Store(Path(folder))))
            desktop.save_preference(store, False)
            self.assertFalse(desktop.load_preference(store))
            for name in ("settings.json", "nodes.json", "runtime.json"):
                self.assertEqual((store.home / name).read_text(), "invalid-private-file")

    def test_invalid_or_future_preferences_cannot_enable_or_destroy_future_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            for value in ({}, [], {"schema": True, "close_docker_desktop": True}, {"schema": 1, "close_docker_desktop": "false"}, {"schema": 99, "close_docker_desktop": True}):
                with self.subTest(value=value):
                    store.write(desktop.PREFERENCES, value)
                    with self.assertRaises(SPXError):
                        desktop.load_preference(store)
            original = (store.home / desktop.PREFERENCES).read_bytes()
            with self.assertRaises(SPXError):
                desktop.save_preference(store, True)
            self.assertEqual((store.home / desktop.PREFERENCES).read_bytes(), original)

    def test_denied_preference_write_preserves_old_selection_without_error_echo(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            desktop.save_preference(store, False)
            with patch.object(store, "write", side_effect=PermissionError("private-fixture-secret")):
                with self.assertRaises(SPXError) as caught:
                    desktop.save_preference(store, True)
            self.assertNotIn("private-fixture-secret", str(caught.exception))
            self.assertFalse(desktop.load_preference(store))
            with self.assertRaises(SPXError):
                desktop.save_preference(store, "true")

    def test_normal_shutdown_is_local_bounded_verified_and_has_no_runtime_env(self):
        replies = [result("running"), result(output=""), result("stopped")]
        with patch.object(desktop.subprocess, "run", side_effect=replies) as run, patch.dict("os.environ", {"DOCKER_HOST": "ssh://other", "DOCKER_CONTEXT": "foreign"}):
            progress = []
            outcome = desktop.stop_desktop(self.docker, progress.append, windows=True)
        self.assertTrue(outcome["docker_desktop_stopped"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["docker.exe", "desktop", "status", "--format", "json"])
        self.assertEqual(commands[1][:4], ["docker.exe", "desktop", "stop", "--timeout"])
        self.assertEqual(commands[2], commands[0])
        self.assertGreaterEqual(int(commands[1][-1]), 1)
        for call in run.call_args_list:
            self.assertLessEqual(call.kwargs["timeout"], 60)
            self.assertNotIn("DOCKER_HOST", call.kwargs["env"])
            self.assertNotIn("DOCKER_CONTEXT", call.kwargs["env"])
            self.assertNotIn("PRIVATE_SESSION", call.kwargs["env"])
            self.assertNotIn("shell", call.kwargs)
        self.assertTrue(progress)
        self.assertFalse(outcome["already_stopped"])

    def test_already_stopped_requires_explicit_evidence_and_sends_no_stop(self):
        with patch.object(desktop.subprocess, "run", return_value=result("stopped", code=1)) as run:
            outcome = desktop.stop_desktop(self.docker, windows=True)
        self.assertTrue(outcome["already_stopped"])
        self.assertEqual(run.call_count, 1)

    def test_unknown_status_and_unsupported_cli_never_attempt_stop_or_echo_output(self):
        for reply in (result(output="private-fixture-secret", code=1), result(output="[]"), result("unknown"), result("running", code=1)):
            with self.subTest(reply=reply), patch.object(desktop.subprocess, "run", return_value=reply) as run:
                with self.assertRaises(desktop.DesktopShutdownError) as caught:
                    desktop.stop_desktop(self.docker, windows=True)
                self.assertEqual(caught.exception.code, "status")
                self.assertNotIn("private-fixture-secret", str(caught.exception))
                self.assertEqual(run.call_count, 1)

    def test_paused_desktop_is_closed_normally(self):
        with patch.object(desktop.subprocess, "run", side_effect=[result("paused"), result(output=""), result("stopped")]) as run:
            self.assertTrue(desktop.stop_desktop(self.docker, windows=True)["docker_desktop_stopped"])
        self.assertEqual(run.call_args_list[1].args[0][2], "stop")

    def test_stopping_desktop_is_only_observed_without_second_stop(self):
        with patch.object(desktop.subprocess, "run", side_effect=[result("stopping"), result("stopped")]) as run:
            self.assertTrue(desktop.stop_desktop(self.docker, windows=True)["docker_desktop_stopped"])
        self.assertTrue(all(call.args[0][2] == "status" for call in run.call_args_list))

    def test_stop_error_is_not_success_without_stopped_evidence(self):
        with patch.object(desktop.subprocess, "run", side_effect=[result("running"), result(output="", code=2), result("running")]):
            with self.assertRaises(desktop.DesktopShutdownError) as caught:
                desktop.stop_desktop(self.docker, windows=True)
        self.assertEqual(caught.exception.code, "stop")
        self.assertNotIn("private-fixture-secret", str(caught.exception))

    def test_accepted_request_can_finish_even_when_cli_reports_error(self):
        for failure in (result(output="", code=2), subprocess.TimeoutExpired(["docker.exe"], 1)):
            with self.subTest(failure=failure), patch.object(desktop.subprocess, "run", side_effect=[result("running"), failure, result("stopped")]) as run:
                self.assertTrue(desktop.stop_desktop(self.docker, windows=True)["docker_desktop_stopped"])
                self.assertEqual(run.call_count, 3)

    def test_polling_has_global_deadline_and_never_forces_shutdown(self):
        now = [0.0]
        clock = SimpleNamespace(monotonic=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        replies = iter([result("running"), result(output="")])
        def reply(*args, **kwargs):
            return next(replies, result("stopping"))
        with patch.object(desktop, "time", clock), patch.object(desktop.subprocess, "run", side_effect=reply) as run:
            with self.assertRaises(desktop.DesktopShutdownError) as caught:
                desktop.stop_desktop(self.docker, windows=True, timeout=2)
        self.assertEqual(caught.exception.code, "timeout")
        self.assertLessEqual(now[0], 2)
        self.assertFalse(any("--force" in call.args[0] for call in run.call_args_list))

    def test_non_windows_is_noop_and_missing_cli_is_not_claimed_stopped(self):
        with patch.object(desktop.subprocess, "run") as run:
            self.assertTrue(desktop.stop_desktop(self.docker, windows=False)["not_applicable"])
            run.assert_not_called()
            with self.assertRaises(desktop.DesktopShutdownError):
                desktop.stop_desktop(SimpleNamespace(executable=None), windows=True)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
