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
        self.status.write_text(json.dumps({"schema": 1, "renderer": {key: True for key in ("non_root", "no_new_privileges", "no_capabilities", "seccomp", "additional_seccomp_filter", "nested_pid_namespace")}}))

    def test_only_verified_main_gets_graceful_signal_and_waits_for_exit(self):
        with patch.object(self.module.os, "getuid", return_value=self.process.stat().st_uid, create=True), patch.object(self.module.os, "kill", side_effect=lambda pid, signum: shutil.rmtree(self.process)) as kill:
            self.assertEqual(self.module.close(self.status, self.root), {"requested": True, "exited": True})
        kill.assert_called_once_with(123, signal.SIGINT)

    def test_pid_one_renderer_foreign_command_and_ipc_launch_never_receive_signal(self):
        original = self.command.read_bytes()
        self.assertFalse(self.module.main_process(self.root, 1))
        self.assertFalse(self.module.main_process(self.root, True))
        for command in (b"python3\0", original + b"--type=renderer\0", original + b"--new-tab\0", original + b"--headless\0", original + b"--no-sandbox\0"):
            with self.subTest(command=command):
                self.command.write_bytes(command)
                with patch.object(self.module.os, "getuid", return_value=self.process.stat().st_uid, create=True), patch.object(self.module.os, "kill") as kill:
                    self.assertEqual(self.module.close(self.status, self.root)["requested"], False)
                kill.assert_not_called()

    def test_ambiguous_main_process_or_unverified_report_never_gets_signal(self):
        second = self.root / "124"
        second.mkdir()
        (second / "cmdline").write_bytes(self.command.read_bytes())
        with patch.object(self.module.os, "getuid", return_value=self.process.stat().st_uid, create=True), patch.object(self.module.os, "kill") as kill:
            self.assertFalse(self.module.close(self.status, self.root)["requested"])
            kill.assert_not_called()
            shutil.rmtree(second)
            self.status.write_text(json.dumps({"schema": 1, "renderer": {"non_root": True}}))
            self.assertFalse(self.module.close(self.status, self.root)["requested"])
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
