import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.gui_diagnostics import GuiDiagnostics, log
from enge_spx.state import Store
from enge_spx.storage import migrate_home


class GuiDiagnosticsTests(unittest.TestCase):
    def test_windowed_app_records_exception_frames_without_messages_or_locals(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "stderr", None), GuiDiagnostics(directory) as report:
                self.assertTrue(faulthandler.is_enabled())
                try:
                    raise RuntimeError("socks5://private-user:private-password@127.0.0.1:1234")
                except RuntimeError as error:
                    report.capture("test-error", type(error), error, error.__traceback__)
            text = (Path(directory) / "logs/gui.log").read_text(encoding="utf-8")
            self.assertIn("test-error type=RuntimeError", text)
            self.assertIn("test_windowed_app_records_exception_frames", text)
            self.assertNotIn("private-password", text)
            self.assertNotIn("private-user", text)

    def test_logs_follow_successful_migration_without_open_file_leftovers(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(directory) / "local")}):
            store = Store(Path(directory) / "source")
            target = Path(directory) / "target"
            with GuiDiagnostics(store.home) as report:
                with report.suspended_for_migration():
                    result = migrate_home(store, target, stop=lambda: None)
                self.assertEqual(report.home, target.resolve())
                self.assertEqual(result["leftovers"], [])
                log.info("after-migration")
            self.assertIn("after-migration", (target / "logs/gui.log").read_text(encoding="utf-8"))
            self.assertFalse((store.home / "logs/gui-fault.log").exists())

    def test_failed_migration_reopens_the_original_fault_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with GuiDiagnostics(directory) as report:
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    with report.suspended_for_migration():
                        raise RuntimeError("cancelled")
                self.assertTrue(faulthandler.is_enabled())
                log.info("after-cancellation")
            self.assertIn("after-cancellation", (Path(directory) / "logs/gui.log").read_text(encoding="utf-8"))

    def test_fatal_exit_writes_a_trace_even_without_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            script = """
import os
import sys
from enge_spx.gui_diagnostics import GuiDiagnostics
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
else:
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
sys.stderr = None
with GuiDiagnostics(sys.argv[1]):
    os.abort()
"""
            result = subprocess.run([sys.executable, "-c", script, directory], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            text = (Path(directory) / "logs/gui-fault.log").read_text(encoding="utf-8")
            self.assertIn("ENGE SPX", text)
            self.assertTrue("Fatal Python error" in text or "Windows fatal exception" in text, text)
            self.assertIn("<module>", text)


if __name__ == "__main__":
    unittest.main()
