from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.__main__ import main


class NetworkCLITests(unittest.TestCase):
    def invoke(self, home, *args):
        output, error = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["spx", "--data", str(home), "network-check", *args]), redirect_stdout(output), redirect_stderr(error):
            result = main()
        return result, output.getvalue(), error.getvalue()

    def test_unprepared_cli_never_starts_docker_or_browser(self):
        with tempfile.TemporaryDirectory() as folder, patch("enge_spx.network_diagnostics.host_facts", return_value={"scope": "control_host; read-only"}), patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Unprepared diagnostics called Docker")):
            code, output, error = self.invoke(folder)
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["status"], "not_ready")

    def test_export_is_json_and_unsafe_or_failed_checks_return_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            for state in ("checked", "partial", "unsafe", "failed"):
                report = {"schema": 1, "status": state, "objects": {"session": {"address": "IPv4#anonymous"}}}
                with patch("enge_spx.engine.Engine.network_diagnostics", return_value=report) as collect:
                    code, output, error = self.invoke(folder, "--skip-browser", "--output", str(path))
                self.assertEqual(code, 2 if state in ("unsafe", "failed") else 0, error)
                self.assertEqual(json.loads(path.read_text()), report)
                self.assertEqual(json.loads(output), report)
                collect.assert_called_once_with(browser=False)


if __name__ == "__main__":
    unittest.main()
