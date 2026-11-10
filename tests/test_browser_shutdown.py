import importlib.util
import json
from pathlib import Path
import shutil
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch

from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.engine import Engine
from enge_spx.state import Store, SPXError


class BrowserShutdownTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("spx_browser_shutdown", PACKAGE_RESOURCES / "checks/browser_shutdown.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.status = self.root / "status.json"
        self.process = self.root / "123"
        self.process.mkdir()
        self.command = self.process / "cmdline"
        self.command.write_bytes(b"/usr/lib/chromium/chromium\0--user-data-dir=/home/workspace/.config/chromium-spx\0")
        self.status.write_text(json.dumps({"renderer": {"browser_pid": 123}}))

    def test_only_verified_main_gets_graceful_signal_and_waits_for_exit(self):
        with patch.object(self.module.os, "getuid", return_value=self.process.stat().st_uid, create=True), patch.object(self.module.os, "kill", side_effect=lambda pid, signum: shutil.rmtree(self.process)) as kill:
            self.assertEqual(self.module.close(self.status, self.root), {"requested": True, "exited": True})
        kill.assert_called_once_with(123, signal.SIGINT)

    def test_pid_one_renderer_foreign_command_and_bad_record_never_receive_signal(self):
        for pid, command in ((1, b"/usr/lib/chromium/chromium\0--user-data-dir=/home/workspace/.config/chromium-spx\0"), (123, b"python3\0"), (123, self.command.read_bytes() + b"--type=renderer\0"), (True, b"chromium\0")):
            with self.subTest(pid=pid, command=command):
                self.status.write_text(json.dumps({"renderer": {"browser_pid": pid}}))
                self.command.write_bytes(command)
                with patch.object(self.module.os, "getuid", return_value=self.process.stat().st_uid, create=True), patch.object(self.module.os, "kill") as kill:
                    self.assertEqual(self.module.close(self.status, self.root)["requested"], False)
                kill.assert_not_called()

    def test_failed_preclose_never_prevents_owned_browser_stop(self):
        engine = Engine(Store(self.root / "data"))
        engine.inspect = Mock(return_value={"Id": "owned-browser", "State": {"Running": True}})
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            if args[0] == "exec":
                raise SPXError("Synthetic graceful close failed")
        engine.docker.run = Mock(side_effect=run)
        self.assertEqual(engine.stop_browser()["browser"], "stopped")
        self.assertEqual([row[0] for row in calls], ["exec", "stop"])


if __name__ == "__main__":
    unittest.main()
