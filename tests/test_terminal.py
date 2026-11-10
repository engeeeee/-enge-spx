import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from enge_spx import terminal
from enge_spx.state import SPXError


class TerminalTests(unittest.TestCase):
    def test_windows_quoting_round_trip(self):
        argv = ["", "plain", "two words", "项目 & name", r"C:\Program Files\Docker\docker.exe", "a\"b", "ends with slash\\", "';&|$()", "\\\\\"quoted"]
        self.assertEqual(terminal.split_arguments(subprocess.list2cmdline(argv)), argv)
        with self.assertRaises(SPXError):
            terminal.split_arguments('--title "unclosed')

    def test_legacy_terminal_setting_uses_generic_launcher_without_losing_its_command(self):
        command = [r"C:\Program Files\Docker\docker.exe", "--context", "desktop-linux", "exec", "-it", "--env", "VALUE=a;echo injected", "container", "claude"]
        with patch.object(terminal, "resolve", return_value=("custom", "pebrel.exe")), patch.object(terminal, "discover", return_value="pebrel.exe"):
            migrated = terminal.validate({"kind": "pebrel"})
            self.assertEqual(migrated["kind"], "custom")
            self.assertEqual(migrated["arguments"], terminal.LEGACY_ARGUMENTS)
            argv, flags = terminal.launch_command({"kind": "pebrel"}, command, r"D:\项目 & spaces", "ENGE SPX · claude")
        self.assertEqual(argv[:8], ["pebrel.exe", "--working-directory", r"D:\项目 & spaces", "--title", "ENGE SPX · claude", "--hold", "-e", command[0]])
        self.assertEqual(argv[7:], command)
        self.assertFalse(flags)
        self.assertNotIn("cmd.exe", argv)

    def test_auto_selects_standard_terminals_and_explicit_selection_never_falls_back(self):
        self.assertNotIn("pebrel", terminal.PRESETS.values())
        with patch.object(terminal, "discover", side_effect=lambda kind: "wt.exe" if kind == "wt" else "powershell.exe") as discover:
            self.assertEqual(terminal.resolve({"kind": "auto"}), ("wt", "wt.exe"))
            discover.assert_called_once_with("wt")
        with patch.object(terminal, "discover", return_value=None) as discover:
            with self.assertRaises(SPXError):
                terminal.resolve({"kind": "pwsh"})
            discover.assert_called_once_with("pwsh")

    def test_auto_falls_through_only_standard_terminals_in_order(self):
        with patch.object(terminal, "discover", side_effect=lambda kind: "powershell.exe" if kind == "powershell" else None) as discover:
            self.assertEqual(terminal.resolve({"kind": "auto"}), ("powershell", "powershell.exe"))
        self.assertEqual([call.args[0] for call in discover.call_args_list], ["wt", "pwsh", "powershell"])

    def test_legacy_explicit_path_needs_no_discovery_and_migration_is_idempotent(self):
        original = {"kind": "pebrel", "executable": r"D:\My Terminal\pebrel.exe"}
        with patch.object(terminal, "discover", side_effect=AssertionError("Explicit selection must remain explicit")):
            migrated = terminal.validate(original)
            self.assertEqual(terminal.validate(migrated), migrated)
        self.assertEqual(migrated["kind"], "custom")
        self.assertEqual(migrated["executable"], original["executable"])
        self.assertEqual(original["kind"], "pebrel")

    def test_custom_launch_does_not_infer_flags_from_executable_name(self):
        for executable in ("pebrel.exe", "other-terminal.exe"):
            config = {"kind": "custom", "executable": executable, "arguments": "--run {command}"}
            with self.subTest(executable=executable), patch.object(terminal, "resolve", return_value=("custom", executable)):
                argv, _ = terminal.launch_command(config, ["spx.exe", "attach"], "D:/project", "title")
                self.assertEqual(argv, [executable, "--run", "spx.exe", "attach"])

    def test_powershell_encodes_every_child_argument(self):
        command = [r"C:\Docker's tools\docker.exe", "--context", "local", "exec", "--env", "VALUE='; Write-Host injected; '", "work", "claude"]
        with patch.object(terminal, "resolve", return_value=("pwsh", "pwsh.exe")):
            argv, _ = terminal.launch_command({"kind": "pwsh"}, command, "D:/project", "title")
        script = base64.b64decode(argv[-1]).decode("utf-16le")
        self.assertEqual(script, "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in command))
        self.assertNotIn("cmd.exe", argv)

    def test_custom_template_expands_command_once_as_separate_arguments(self):
        config = {"kind": "custom", "executable": "thirdparty.exe", "arguments": '--cwd "{project}" --title "{title}" -e {command}'}
        with patch.object(terminal, "resolve", return_value=("custom", "thirdparty.exe")):
            argv, _ = terminal.launch_command(config, ["docker.exe", "exec", "a&b", "claude"], "D:/项目 & spaces", 'A "title"')
        self.assertEqual(argv, ["thirdparty.exe", "--cwd", "D:/项目 & spaces", "--title", 'A "title"', "-e", "docker.exe", "exec", "a&b", "claude"])
        for arguments in ("", "-e {command} {command}", "-e prefix{command}", "{unknown} {command}"):
            with self.subTest(arguments=arguments), self.assertRaises(SPXError):
                terminal.validate({**config, "arguments": arguments})

    def test_windows_terminal_wraps_child_semicolons_in_encoded_powershell(self):
        command = ["docker.exe", "exec", "--env", "A=one;two", "work", "claude"]
        with patch.object(terminal, "resolve", return_value=("wt", "wt.exe")), patch.object(terminal, "discover", return_value="powershell.exe"):
            argv, _ = terminal.launch_command({"kind": "wt"}, command, "D:/project;name", "title;extra")
        self.assertTrue(all(";" not in arg for arg in argv))
        self.assertIn("'A=one;two'", base64.b64decode(argv[-1]).decode("utf-16le"))
        self.assertIn("Set-Location -LiteralPath 'D:/project;name'", base64.b64decode(argv[-1]).decode("utf-16le"))

    @unittest.skipUnless(os.name == "nt", "native Windows process argument handling")
    def test_custom_launcher_native_process_preserves_args_cwd_and_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "项目 & spaces"
            project.mkdir()
            output = project / "result.json"
            script = "import json,os,pathlib,sys; pathlib.Path('result.json').write_text(json.dumps([sys.argv[1:],os.getcwd(),os.environ['SPX_TERMINAL_TEST']]),encoding='utf-8')"
            config = {"kind": "custom", "executable": sys.executable, "arguments": subprocess.list2cmdline(["-c", script, "{command}"])}
            command = ["docker.exe", "--context", "desktop-linux", "exec", "-it", "a;b&c", 'quoted "argument"', "tail\\", "中文"]
            argv, flags = terminal.launch_command(config, command, str(project), "test")
            process = subprocess.Popen(argv, cwd=project, env={**os.environ, "SPX_TERMINAL_TEST": "preserved"}, creationflags=flags)
            self.assertEqual(process.wait(timeout=10), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, [command, str(project), "preserved"])


if __name__ == "__main__":
    unittest.main()
