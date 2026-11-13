import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from enge_spx.local_process import run


class LocalProcessTests(unittest.TestCase):
    def test_captures_separate_bounded_outputs_and_exit_status(self):
        result = run([sys.executable, "-c", "import sys; print('out'); print('err',file=sys.stderr); sys.exit(7)"],
                     timeout=5, env=dict(os.environ))
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), "out")
        self.assertEqual(result.stderr.strip(), "err")
        with self.assertRaises(OSError):
            run([sys.executable, "-c", "print('x'*100)"], timeout=5,
                env=dict(os.environ), limit=64)

    def test_plugin_inheriting_output_cannot_extend_parent_timeout(self):
        # A real owned descendant retains both output handles. On Windows,
        # subprocess.run(capture_output=True) otherwise drains those handles
        # without a deadline after killing the parent. Do not kill the plugin:
        # like the actual read-only status plugin it finishes independently.
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "plugin-finished"
            child = "import time; from pathlib import Path; time.sleep(3); Path(" + repr(str(marker)) + ").write_text('natural-exit')"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "],stdout=sys.stdout,stderr=sys.stderr); time.sleep(30)"
            started = time.monotonic()
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    run([sys.executable, "-c", parent], timeout=.8, env=dict(os.environ))
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 2.5, "An inherited output handle consumed the offline proof budget")
                self.assertFalse(marker.exists())
            finally:
                deadline = time.monotonic() + 8
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
            self.assertEqual(marker.read_text(), "natural-exit")


if __name__ == "__main__":
    unittest.main()
