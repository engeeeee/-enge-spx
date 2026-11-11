from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.__main__ import main


class MeasurementCLITests(unittest.TestCase):
    def invoke(self, home, *args):
        output, error = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["spx", "--data", str(home), "network-test", *args]), redirect_stdout(output), redirect_stderr(error):
            code = main()
        return code, output.getvalue(), error.getvalue()

    def test_unprepared_query_never_starts_or_queries_docker(self):
        with tempfile.TemporaryDirectory() as folder, patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Unexpected Docker access")):
            code, output, error = self.invoke(folder)
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["status"], "not_ready")

    def test_scoped_results_and_export_preserve_failure_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "report.json"
            for status in ("checked", "partial", "failed", "stale", "not_ready"):
                report = {"schema": 1, "kind": "network_performance", "status": status, "notes": ["合成脱敏数据"]}
                with patch("enge_spx.engine.Engine.network_performance", return_value=report) as collect:
                    code, output, error = self.invoke(folder, "--output", str(target))
                self.assertEqual(code, 0 if status in ("checked", "not_ready") else 2, error)
                self.assertEqual(json.loads(output), report)
                self.assertEqual(json.loads(target.read_text()), report)
                collect.assert_called_once_with()

    def test_custom_target_arguments_are_rejected_without_echoing_a_secret_url(self):
        with tempfile.TemporaryDirectory() as folder:
            output, error = io.StringIO(), io.StringIO()
            with patch("sys.argv", ["spx", "--data", folder, "network-test", "--url", "https://private:password@invalid.test"]), redirect_stdout(output), redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                main()
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn("private", error.getvalue())
        self.assertNotIn("password", error.getvalue())


if __name__ == "__main__":
    unittest.main()
