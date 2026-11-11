from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.__main__ import main
from enge_spx.resource_recording import record
from test_resource_recording import Clock, evidence


class RecordingCLITests(unittest.TestCase):
    def invoke(self, root, *args):
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["spx", "--data", str(root / "data"), "resources", "--record", str(root / "report.json"), *args]), redirect_stdout(output), redirect_stderr(errors):
            result = main()
        return result, output.getvalue(), errors.getvalue()

    def test_foreground_record_uses_real_serializer_without_starting_or_stopping_environment(self):
        clock = Clock()
        def measured(provider, **kwargs):
            return record(provider, **kwargs, clock=clock, wait=clock.wait)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("enge_spx.resource_recording.record", side_effect=measured), patch("enge_spx.resource_monitor.Monitor.snapshot", return_value=evidence()), patch("enge_spx.engine.Engine.doctor", side_effect=AssertionError("Unexpected Docker startup")), patch("enge_spx.engine.Engine._stop", side_effect=AssertionError("Unexpected workspace stop")):
                code, out, error = self.invoke(root, "--seconds", "10", "--interval", "5", "--activity", "codex")
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(out)["sample_count"], 2)
            result = json.loads((root / "report.json").read_text())
            self.assertEqual(result["requested"]["activity"], "codex")
            self.assertEqual(result["source"], "cli")
            self.assertNotIn("private-", (root / "report.json").read_text())

    def test_bad_input_is_rejected_without_file_or_secret_echo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for args in (("--seconds", "0"), ("--activity", "socks5://private-password@host")):
                code, out, error = self.invoke(root, *args)
                self.assertEqual(code, 1)
                self.assertFalse((root / "report.json").exists())
                self.assertNotIn("private-password", out + error)

    def test_ctrl_c_saves_valid_partial_measurement_and_returns_130(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("enge_spx.resource_monitor.Monitor.snapshot", side_effect=KeyboardInterrupt()):
                code, out, error = self.invoke(root, "--seconds", "5")
            self.assertEqual(code, 130, error)
            self.assertEqual(json.loads(out)["end_reason"], "interrupted")
            self.assertEqual(json.loads((root / "report.json").read_text())["sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
