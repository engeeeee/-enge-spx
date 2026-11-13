import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from enge_spx.tool_session import command


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "Actual Linux workspace shell")
class ToolSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.environment = {**os.environ, "HOME": str(self.home), "NPM_CONFIG_PREFIX": "/root-owned-prefix", "npm_config_prefix": "/other-prefix"}

    def test_rootless_prefix_precedes_image_tools_and_preserves_literal_arguments(self):
        arguments = ["a;touch SHOULD_NOT_EXIST", "$(false)", "项目 with spaces", "single'quote"]
        code = 'printf "%s\\n" "$NPM_CONFIG_PREFIX" "$npm_config_prefix" "$PATH" "$@"'
        result = subprocess.run(command(["bash", "-c", code, "fixture", *arguments]), env=self.environment,
                                capture_output=True, text=True, timeout=5, cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = result.stdout.splitlines()
        self.assertEqual(rows[:2], [str(self.home / ".local")] * 2)
        self.assertTrue(rows[2].startswith(str(self.home / ".local/bin") + ":"))
        self.assertEqual(rows[3:], arguments)
        self.assertFalse((self.home / "SHOULD_NOT_EXIST").exists())

    def test_cli_exit_codes_remain_exact_and_do_not_open_a_fallback_shell(self):
        result = subprocess.run(command(["bash", "-c", "exit 27"]), env=self.environment,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 27)
        self.assertNotIn("工具已结束", result.stdout)

    def test_gui_tool_update_exit_keeps_terminal_and_resolves_new_user_binary(self):
        # A first tool exits after an update, like Codex. The actual interactive
        # fallback shell must remain, retain its prefix and resolve the newly
        # installed version. Nothing touches host/system tools or real accounts.
        local = self.home / ".local/bin"
        local.mkdir(parents=True)
        tool = local / "codex"
        tool.write_text("#!/bin/sh\nprintf 'updated-version\\n'\n")
        tool.chmod(0o755)
        result = subprocess.run(command(["bash", "-c", "exit 13"], keep_open=True), env=self.environment,
                                input="codex\nprintf '%s\\n' \"$NPM_CONFIG_PREFIX\"\nexit\n",
                                capture_output=True, text=True, timeout=5, cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("退出码 13", result.stdout)
        self.assertIn("updated-version", result.stdout)
        self.assertIn(str(self.home / ".local"), result.stdout)


if __name__ == "__main__":
    unittest.main()
