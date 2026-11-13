"""Regressions for the guard/foreground handoff and single-pass tool startup."""
import errno
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from enge_spx.engine import Engine
from enge_spx.state import SPXError, Store


class WorkspaceLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.store = Store(self.base / "private")
        self.project = self.base / "project"
        self.project.mkdir()

    def engine(self):
        engine = Engine(self.store)
        engine.docker = Mock()
        engine.docker.executable = None
        engine.docker.secret_env = {}
        engine.docker.command.side_effect = lambda *args: ["docker.exe", *args]
        engine.ready = Mock(return_value={"session": "session", "browser_token": "a" * 64})
        engine._browser = Mock(return_value="http://127.0.0.1:12345/vnc.html")
        engine._project = Mock(return_value=({"Id": "project-container"}, "project-key"))
        engine.proxy_env = Mock(return_value=[])
        return engine

    def test_first_command_waits_for_guard_then_prepares_exactly_once(self):
        held, release, finished = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def guard():
            try:
                with self.store.lock():
                    held.set()
                    if not release.wait(3):
                        raise AssertionError("Foreground did not wait for the guard")
            except BaseException as error:
                failures.append(error)
            finally:
                finished.set()
        thread = threading.Thread(target=guard)
        thread.start()
        try:
            self.assertTrue(held.wait(2))
            engine = self.engine()
            engine.log = Mock(side_effect=lambda text: release.set())
            command = engine.tool_command(str(self.project), ["claude", "--continue"])
            self.assertTrue(finished.wait(1))
            self.assertEqual(command[-2:], ["claude", "--continue"])
            self.assertEqual(command.count("project-container"), 1)
            engine.log.assert_called_once()
            engine.ready.assert_called_once()
            engine._browser.assert_called_once()
            engine._project.assert_called_once()
        finally:
            release.set()
            thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures, failures)

    def test_terminal_opens_prepared_viewer_without_reacquiring_after_launch(self):
        for tool in ("claude", "codex", "shell", "login-claude", "login-codex"):
            with self.subTest(tool=tool):
                engine = self.engine()
                # A guard acquires the operation lock just after the host terminal
                # launches. Opening the already prepared viewer must still work.
                held = []
                def launched(*args):
                    lock = self.store.lock()
                    lock.__enter__()
                    held.append(lock)
                try:
                    with patch("enge_spx.engine.os", SimpleNamespace(name="nt")), patch("enge_spx.terminal.resolve"), patch("enge_spx.terminal.launch", side_effect=launched) as launch, patch("enge_spx.engine.webbrowser.open") as viewer:
                        engine.terminal(str(self.project), tool)
                    launch.assert_called_once()
                    self.assertNotIn("a" * 64, repr(launch.call_args))
                    self.assertNotIn("SPX_BROWSER_TOKEN", launch.call_args.args[4])
                    viewer.assert_called_once_with(engine._browser.return_value)
                    engine.ready.assert_called_once()
                    engine._browser.assert_called_once()
                    engine._project.assert_called_once()
                finally:
                    for lock in held:
                        lock.__exit__(None, None, None)

    def test_failed_route_check_never_launches_or_retries_the_tool(self):
        engine = self.engine()
        engine.ready.side_effect = SPXError("连接已停止，请重新确认。")
        with patch("enge_spx.engine.os", SimpleNamespace(name="nt")), patch("enge_spx.terminal.resolve"), patch("enge_spx.terminal.launch") as launch, patch("enge_spx.engine.webbrowser.open") as viewer:
            with self.assertRaisesRegex(SPXError, "连接已停止"):
                engine.terminal(str(self.project), "codex")
        engine.ready.assert_called_once()
        engine._browser.assert_not_called()
        engine._project.assert_not_called()
        launch.assert_not_called()
        viewer.assert_not_called()

    def test_lock_wait_is_bounded_and_notified_once(self):
        waiting = Mock()
        started = time.monotonic()
        with self.store.lock():
            with self.assertRaises(SPXError):
                with self.store.lock(timeout=.05, on_wait=waiting):
                    self.fail("A held lock must never be bypassed")
        waiting.assert_called_once()
        self.assertLess(time.monotonic() - started, 2)
        with self.store.lock():
            pass

    def test_unrelated_lock_errors_are_not_retried(self):
        target = "msvcrt.locking" if os.name == "nt" else "fcntl.flock"
        waiting = Mock()
        with patch(target, side_effect=OSError(errno.EBADF, "invalid handle")) as acquire:
            with self.assertRaises(OSError):
                with self.store.lock(timeout=30, on_wait=waiting):
                    self.fail("Invalid handles must fail immediately")
        acquire.assert_called_once()
        waiting.assert_not_called()


if __name__ == "__main__":
    unittest.main()
