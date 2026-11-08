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

    def test_pebrel_passes_docker_argv_without_a_shell(self):
        command = [r"C:\Program Files\Docker\docker.exe", "--context", "desktop-linux", "exec", "-it", "--env", "VALUE=a;echo injected", "container", "claude"]
        with patch.object(terminal, "resolve", return_value=("pebrel", "pebrel.exe")):
            argv, flags = terminal.launch_command({"kind": "pebrel"}, command, r"D:\项目 & spaces", "ENGE SPX · claude")
        self.assertEqual(argv[:8], ["pebrel.exe", "--working-directory", r"D:\项目 & spaces", "--title", "ENGE SPX · claude", "--hold", "-e", command[0]])
        self.assertEqual(argv[7:], command)
        self.assertFalse(flags)
        self.assertNotIn("cmd.exe", argv)

    def test_auto_prefers_pebrel_and_explicit_selection_never_falls_back(self):
        with patch.object(terminal, "discover", side_effect=lambda kind: "pebrel.exe" if kind == "pebrel" else "powershell.exe") as discover:
            self.assertEqual(terminal.resolve({"kind": "auto"}), ("pebrel", "pebrel.exe"))
            discover.assert_called_once_with("pebrel")
        with patch.object(terminal, "discover", return_value=None) as discover:
            with self.assertRaises(SPXError):
                terminal.resolve({"kind": "pebrel"})
            discover.assert_called_once_with("pebrel")

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
