import json
import threading
import unittest

from enge_spx.exit_diagnostics import add_check, capture_checks, failure_report


class ExitDiagnosticsTests(unittest.TestCase):
    def test_reports_are_bounded_and_omit_errors_paths_and_command_output(self):
        with capture_checks() as checks:
            for _ in range(100):
                add_check("offline", "wsl_running", "unavailable", PermissionError(13, "private-password C:/private-path"))
            add_check("socks5://private-user:private-password@host", "stage", "failed")
            report = failure_report("workspace", checks, RuntimeError("private-exception-output"))
        self.assertEqual(len(report["checks"]), 64)
        self.assertEqual(report["checks"][0]["os_code"], 13)
        self.assertEqual(report["checks"][0]["error_type"], "PermissionError")
        self.assertFalse(report["workspace_stop_verified"])
        self.assertIn("version", report)
        text = json.dumps(report)
        for private in ("private-password", "private-user", "private-path", "private-exception-output"):
            self.assertNotIn(private, text)

    def test_nested_checks_and_other_workers_do_not_mix_exit_evidence(self):
        with capture_checks() as outer:
            add_check("offline", "outer", "first")
            with capture_checks() as inner:
                add_check("offline", "inner", "second")
            def worker():
                add_check("offline", "unrelated", "third")
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(1)
            add_check("offline", "outer", "last")
        self.assertEqual([row["result"] for row in outer], ["first", "last"])
        self.assertEqual([row["result"] for row in inner], ["second"])


if __name__ == "__main__":
    unittest.main()
