import ctypes
import json
import os
from pathlib import Path
import subprocess
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from enge_spx import desktop_offline as offline
from enge_spx import process_metrics


class OfflineDesktopTests(unittest.TestCase):
    def proof(self):
        patches = {
            "os": SimpleNamespace(name="nt"),
            "_wsl_enabled": Mock(return_value=True),
            "_kernel": Mock(return_value=Mock()),
            "_desktop_absent": Mock(return_value=True),
            "_pipe_absent": Mock(return_value=True),
            "_wsl_path": Mock(return_value="C:/Windows/System32/wsl.exe"),
            "_distributions": Mock(side_effect=[{"docker-desktop", "ubuntu"}, {"ubuntu"}]),
        }
        return patches

    def test_closed_backend_with_other_running_distribution_is_verified_without_stopping_it(self):
        proof = self.proof()
        with patch.multiple(offline, **proof):
            self.assertTrue(offline.stopped())
        self.assertEqual(proof["_desktop_absent"].call_count, 2)
        self.assertEqual(proof["_pipe_absent"].call_count, 2)
        self.assertEqual([call.args[1] for call in proof["_distributions"].call_args_list], [False, True])
        self.assertTrue(all(0 < call.args[2] <= 8 for call in proof["_distributions"].call_args_list))

    def test_failure_logs_the_exact_stage_without_private_output(self):
        for stage, setup in (("wsl2_configuration", lambda p: setattr(p["_wsl_enabled"], "return_value", False)),
                             ("desktop_processes", lambda p: setattr(p["_desktop_absent"], "return_value", False)),
                             ("engine_pipe", lambda p: setattr(p["_pipe_absent"], "return_value", False)),
                             ("wsl_registered", lambda p: setattr(p["_distributions"], "side_effect", subprocess.TimeoutExpired(["private-command"], 3, output=b"private-stdout", stderr=b"private-stderr")))):
            proof = self.proof()
            setup(proof)
            with self.subTest(stage=stage), patch.multiple(offline, **proof), self.assertLogs("enge_spx.gui", level="INFO") as records:
                self.assertFalse(offline.stopped())
            messages = "\n".join(records.output)
            self.assertIn("stage=" + stage, messages)
            for secret in ("private-command", "private-stdout", "private-stderr"):
                self.assertNotIn(secret, messages)

    def test_gui_log_records_unavailable_proof_without_user_distro_names(self):
        from enge_spx.gui_diagnostics import GuiDiagnostics
        proof = self.proof()
        proof["_distributions"].side_effect = [{"docker-desktop", "private-distro"}, {"docker-desktop", "private-distro"}]
        with tempfile.TemporaryDirectory() as directory:
            with GuiDiagnostics(directory), patch.multiple(offline, **proof):
                self.assertFalse(offline.stopped())
            text = (Path(directory) / "logs/gui.log").read_text(encoding="utf-8")
            self.assertIn("stage=wsl_running result=docker_distro_running", text)
            self.assertNotIn("private-distro", text)

    def test_missing_config_existing_process_or_pipe_never_proves_stopped(self):
        for target in ("_wsl_enabled", "_desktop_absent", "_pipe_absent"):
            with self.subTest(target=target):
                proof = self.proof()
                proof[target].return_value = False
                with patch.multiple(offline, **proof):
                    self.assertFalse(offline.stopped())
                proof["_distributions"].assert_not_called()

    def test_running_docker_distro_unregistered_or_inconsistent_wsl_output_is_unknown(self):
        for registered, running in (({"docker-desktop"}, {"docker-desktop"}),
                                    ({"docker-desktop", "docker-desktop-data"}, {"docker-desktop-data"}),
                                    ({"ubuntu"}, set()),
                                    ({"docker-desktop"}, {"unregistered"})):
            with self.subTest(registered=registered, running=running):
                proof = self.proof()
                proof["_distributions"].side_effect = [registered, running]
                with patch.multiple(offline, **proof):
                    self.assertFalse(offline.stopped())

    def test_backend_or_pipe_returning_before_final_check_invalidates_proof(self):
        for target in ("_desktop_absent", "_pipe_absent"):
            proof = self.proof()
            proof[target].side_effect = [True, False]
            with self.subTest(target=target), patch.multiple(offline, **proof):
                self.assertFalse(offline.stopped())

    def test_wait_allows_pipe_shutdown_to_precede_process_and_wsl_teardown(self):
        now = [0.0]
        clock = SimpleNamespace(monotonic=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay))
        proof = self.proof()
        proof["_desktop_absent"].side_effect = [False, True, True, True]
        proof["_distributions"].side_effect = [{"docker-desktop"}, {"docker-desktop"}, {"docker-desktop"}, set()]
        with patch.multiple(offline, **proof), patch.object(offline, "time", clock):
            self.assertTrue(offline.stopped(timeout=1, wait=True))
        self.assertGreater(now[0], 0)
        self.assertLessEqual(now[0], 1)
        self.assertEqual(proof["_distributions"].call_count, 4)

    def test_wait_never_turns_a_missing_pipe_into_success_if_backend_remains(self):
        now = [0.0]
        clock = SimpleNamespace(monotonic=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay))
        proof = self.proof()
        proof["_desktop_absent"].return_value = False
        with patch.multiple(offline, **proof), patch.object(offline, "time", clock):
            self.assertFalse(offline.stopped(timeout=.5, wait=True))
        self.assertEqual(now[0], .5)
        proof["_distributions"].assert_not_called()

    def test_denied_incomplete_and_timed_out_queries_are_not_absence(self):
        for target, error in (("_desktop_absent", PermissionError("private-fixture-secret")),
                              ("_pipe_absent", OSError("private-fixture-secret")),
                              ("_distributions", subprocess.TimeoutExpired([], 3)),
                              ("_distributions", UnicodeError("private-fixture-secret"))):
            proof = self.proof()
            proof[target].side_effect = error
            with self.subTest(target=target, error=type(error).__name__), patch.multiple(offline, **proof):
                self.assertFalse(offline.stopped())

    def test_deadline_non_windows_and_expired_budget_never_claim_stop(self):
        proof = self.proof()
        with patch.multiple(offline, **proof), patch.object(offline.time, "monotonic", side_effect=[0, 0, 0, 9]):
            self.assertFalse(offline.stopped(timeout=8))
        with patch.multiple(offline, **self.proof()):
            self.assertFalse(offline.stopped(timeout=0))
        proof = self.proof()
        proof["os"] = SimpleNamespace(name="posix")
        with patch.multiple(offline, **proof):
            self.assertFalse(offline.stopped())
        proof["_kernel"].assert_not_called()

    def test_preflight_distinguishes_windows_budget_exhaustion_from_platform(self):
        from enge_spx.exit_diagnostics import capture_checks
        for name, budget, result in (("nt", 0, "budget_expired"), ("posix", 8, "unsupported_platform")):
            with self.subTest(name=name), patch.object(offline, "os", SimpleNamespace(name=name)), patch.object(offline, "_observe") as observe, capture_checks() as checks:
                self.assertFalse(offline.stopped(timeout=budget))
            observe.assert_not_called()
            self.assertEqual(list(checks), [{"component": "offline", "stage": "preflight", "result": result}])

    def test_only_file_not_found_is_absent_not_access_denied_busy_or_timeout(self):
        kernel = Mock()
        for present, error, expected in ((True, 0, False), (False, 2, True), (False, 5, False), (False, 121, False), (False, 231, False), (False, 3, False)):
            kernel.WaitNamedPipeW.return_value = present
            with self.subTest(error=error), patch.object(ctypes, "set_last_error", create=True), patch.object(ctypes, "get_last_error", return_value=error, create=True):
                self.assertEqual(offline._pipe_absent(kernel), expected)
            kernel.WaitNamedPipeW.assert_called_with(offline.PIPE, 1)

    def test_process_absence_requires_complete_enumeration_and_ignores_shared_wsl(self):
        with patch.object(offline, "desktop_processes", return_value=[{"scope": "wsl"}]) as snapshot:
            self.assertTrue(offline._desktop_absent())
            snapshot.assert_called_once_with(strict=True)
        with patch.object(offline, "desktop_processes", return_value=[{"scope": "desktop"}]):
            self.assertFalse(offline._desktop_absent())

    def test_strict_snapshot_rejects_partial_enumeration_and_closes_handle(self):
        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]
        kernel = Mock()
        kernel.CreateToolhelp32Snapshot.return_value = 123
        def first(handle, pointer):
            pointer._obj.th32ProcessID = 1
            pointer._obj.szExeFile = "unrelated.exe"
            return True
        kernel.Process32FirstW.side_effect = first
        kernel.Process32NextW.return_value = False
        with patch.object(process_metrics, "os", SimpleNamespace(name="nt")), patch.object(process_metrics, "_windows", return_value=(kernel, None, None, Entry, None)), patch.object(ctypes, "set_last_error", create=True), patch.object(ctypes, "get_last_error", return_value=5, create=True):
            with self.assertRaises(OSError):
                process_metrics.desktop_processes(strict=True)
        kernel.CloseHandle.assert_called_once_with(123)
        kernel.CloseHandle.reset_mock()
        with patch.object(process_metrics, "os", SimpleNamespace(name="nt")), patch.object(process_metrics, "_windows", return_value=(kernel, None, None, Entry, None)), patch.object(ctypes, "set_last_error", create=True), patch.object(ctypes, "get_last_error", return_value=18, create=True):
            self.assertEqual(process_metrics.desktop_processes(strict=True), [])
        kernel.CloseHandle.assert_called_once_with(123)
        kernel.CreateToolhelp32Snapshot.return_value = ctypes.c_void_p(-1).value
        with patch.object(process_metrics, "os", SimpleNamespace(name="nt")), patch.object(process_metrics, "_windows", return_value=(kernel, None, None, Entry, None)):
            with self.assertRaises(OSError):
                process_metrics.desktop_processes(strict=True)
            self.assertEqual(process_metrics.desktop_processes(), [])

    def test_explicit_wsl_setting_accepts_current_legacy_and_wrapped_booleans(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "Docker"
            config.mkdir()
            with patch.object(offline, "os", SimpleNamespace(environ={"APPDATA": folder})):
                for value in ({"wslEngineEnabled": True}, {"WslEngineEnabled": True}, {"wslEngineEnabled": {"value": True}}):
                    (config / "settings-store.json").write_text(json.dumps(value), encoding="utf-8-sig")
                    self.assertTrue(offline._wsl_enabled())
                (config / "settings-store.json").unlink()
                (config / "settings.json").write_text('{"wslEngineEnabled":true}')
                self.assertTrue(offline._wsl_enabled())

    def test_unknown_or_corrupt_current_settings_do_not_use_stale_legacy_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "Docker"
            config.mkdir()
            (config / "settings.json").write_text('{"wslEngineEnabled":true}')
            with patch.object(offline, "os", SimpleNamespace(environ={"APPDATA": folder})):
                for value in ({}, [], {"wslEngineEnabled": False}, {"wslEngineEnabled": "true"}, {"wslEngineEnabled": True, "WslEngineEnabled": False}):
                    (config / "settings-store.json").write_text(json.dumps(value))
                    self.assertFalse(offline._wsl_enabled())
                (config / "settings-store.json").write_text("invalid")
                with self.assertRaises(ValueError):
                    offline._wsl_enabled()
                (config / "settings-store.json").write_bytes(b" " * (1024 * 1024 + 1))
                self.assertFalse(offline._wsl_enabled())

    def test_wsl_output_handles_native_utf16_and_utf8_without_logging_names(self):
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le"):
            result = subprocess.CompletedProcess([], 0, "docker-desktop\r\nUbuntu\r\n".encode(encoding), b"private-fixture-secret")
            with self.subTest(encoding=encoding), patch.object(offline.subprocess, "run", return_value=result) as run:
                self.assertEqual(offline._distributions("C:/Windows/System32/wsl.exe", True, 9), {"docker-desktop", "ubuntu"})
            self.assertEqual(run.call_args.args[0], ["C:/Windows/System32/wsl.exe", "--list", "--quiet", "--running"])
            self.assertEqual(run.call_args.kwargs["timeout"], 3)
            self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertNotIn("input", run.call_args.kwargs)

    def test_failed_malformed_oversized_wsl_query_never_becomes_an_empty_list(self):
        for output, code in ((b"", 1), (b"x" * 65537, 0), (b"\xff", 0), ("text instead of bytes", 0), (b"docker-desktop\x01", 0)):
            result = subprocess.CompletedProcess([], code, output, b"private-fixture-secret")
            with self.subTest(code=code, output_type=type(output).__name__), patch.object(offline.subprocess, "run", return_value=result):
                with self.assertRaises((OSError, ValueError)) as error:
                    offline._distributions("C:/Windows/System32/wsl.exe", True, 2)
                self.assertNotIn("private-fixture-secret", str(error.exception))
        with patch.object(offline.subprocess, "run") as run:
            with self.assertRaises(TimeoutError):
                offline._distributions("C:/Windows/System32/wsl.exe", True, 0)
            run.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Native Windows pipe API")
    def test_native_pipe_presence_and_absence_without_touching_docker(self):
        from ctypes import wintypes as w
        kernel = offline._kernel()
        kernel.CreateNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p]
        kernel.CreateNamedPipeW.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        with patch.object(offline, "PIPE", r"\\.\pipe\enge-spx-test-" + uuid.uuid4().hex):
            self.assertTrue(offline._pipe_absent(kernel))
            handle = kernel.CreateNamedPipeW(offline.PIPE, 3, 0, 1, 1024, 1024, 0, None)
            self.assertNotIn(handle, (None, ctypes.c_void_p(-1).value))
            try:
                self.assertFalse(offline._pipe_absent(kernel))
            finally:
                kernel.CloseHandle(handle)
            self.assertTrue(offline._pipe_absent(kernel))

    @unittest.skipUnless(os.name == "nt", "Native Windows process API")
    def test_native_strict_process_snapshot_and_system_wsl_location(self):
        rows = process_metrics.desktop_processes(strict=True)
        self.assertTrue(all(row["scope"] in ("desktop", "wsl") for row in rows))
        # Location is derived from Windows, not the caller's PATH. WSL may not
        # be installed on a runner; a missing file remains an explicit error.
        try:
            path = Path(offline._wsl_path(offline._kernel()))
        except OSError:
            return
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.parent.name.casefold(), "system32")

    @unittest.skipUnless(os.name == "nt", "Native Windows process teardown")
    def test_native_owned_desktop_process_finishes_after_the_pipe_disappears(self):
        from desktop_harness import fake_desktop, environment
        if any(row["scope"] == "desktop" for row in process_metrics.desktop_processes(strict=True)):
            self.skipTest("Does not operate on an already running real Desktop")
        with fake_desktop() as (base, cli):
            child = subprocess.Popen([str(base / "Docker App/Docker Desktop.exe")],
                                     env=environment(base, cli, "cli"),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (base / "ready").exists() and time.monotonic() < deadline:
                    self.assertIsNone(child.poll())
                    time.sleep(.02)
                self.assertTrue((base / "ready").exists())
                # The real process exits on its own timer. WSL evidence is an
                # injected fixture; process/pipe observations are native APIs.
                with patch.object(offline, "PIPE", r"\\.\pipe\enge-spx-test-" + uuid.uuid4().hex), patch.object(offline, "_wsl_enabled", return_value=True), patch.object(offline, "_wsl_path", return_value="fixture"), patch.object(offline, "_distributions", side_effect=[{"docker-desktop"}, set()]):
                    self.assertFalse(offline.stopped())
                    self.assertTrue(offline.stopped(timeout=5, wait=True))
                self.assertEqual(child.wait(timeout=2), 0)
            finally:
                if child.poll() is None:
                    child.kill()  # Only the process owned by this fixture.
                    child.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
