from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.__main__ import main
from enge_spx.state import Store


class WorkspaceCLITests(unittest.TestCase):
    def invoke(self, home, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["spx", "--data", str(home), *args]), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_list_and_create_need_no_docker_and_do_not_copy_or_select_accounts(self):
        with tempfile.TemporaryDirectory() as folder, patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Metadata action queried Docker")):
            code, output, _ = self.invoke(folder, "profiles", "list")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["selected"], "shared")
            code, output, _ = self.invoke(folder, "profiles", "create", "测试身份")
            self.assertEqual(code, 0)
            result = json.loads(output)
            self.assertEqual(result["config"]["selected"], "shared")
            self.assertEqual(result["config"]["profiles"][result["profile"]], "测试身份")

    def test_apply_binds_exact_project_and_restore_keeps_identity_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "project"
            directory.mkdir()
            home = root / "data"
            _, output, _ = self.invoke(home, "profiles", "create", "账号 A")
            identity = json.loads(output)["profile"]
            code, output, _ = self.invoke(home, "--project", str(directory), "profiles", "apply", identity, "--access", "ro")
            self.assertEqual(code, 0)
            config = json.loads(output)
            self.assertEqual(config["selected"], identity)
            self.assertEqual(config["projects"][Store(home).project(str(directory))[1]], {"profile": identity, "access": "ro"})
            code, output, _ = self.invoke(home, "profiles", "restore")
            self.assertEqual(code, 0)
            self.assertIn(identity, json.loads(output)["profiles"])

    def test_malformed_identity_is_rejected_without_echoing_input(self):
        with tempfile.TemporaryDirectory() as folder:
            code, output, error = self.invoke(folder, "profiles", "select", "socks5://user:private-password@proxy")
            self.assertEqual(code, 1)
            self.assertNotIn("private-password", output + error)


if __name__ == "__main__":
    unittest.main()
