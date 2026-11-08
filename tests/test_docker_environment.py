import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.docker_env import environment
from enge_spx.engine import Docker


class DockerEnvironmentTests(unittest.TestCase):
    def test_windows_child_finds_siblings_without_changing_parent_path(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "Docker Desktop/resources/bin/docker.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            source = {"Path": "existing-tools", "DOCKER_CONFIG": "private-config", "PATHEXT": ".EXE;.CMD", "DOCKER_HOST": "remote", "DOCKER_CONTEXT": "other"}
            before = dict(source)
            child = environment(binary, source, windows=True)
            self.assertEqual(child["PATH"].split(";")[0], str(binary.parent.resolve()))
            self.assertIn("existing-tools", child["PATH"])
            self.assertEqual(child["DOCKER_CONFIG"], "private-config")
            self.assertEqual(child["PATHEXT"], ".EXE;.CMD")
            self.assertNotIn("DOCKER_HOST", child)
            self.assertNotIn("DOCKER_CONTEXT", child)
            self.assertNotIn("Path", child)
            self.assertEqual(source, before)

    def test_windows_desktop_helpers_are_found_when_using_a_separate_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            system_bin = base / "Program Files/Docker/Docker/resources/bin"
            system_bin.mkdir(parents=True)
            child = environment(base / "separate/docker.exe", {"PROGRAMFILES": str(base / "Program Files"), "PATH": "existing-tools"}, windows=True)
            self.assertIn(str(system_bin), child["PATH"].split(";"))

    def test_case_insensitive_windows_path_entries_are_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "bin/docker.exe"
            binary.parent.mkdir()
            canonical = str(binary.parent.resolve())
            child = environment(binary, {"PATH": canonical.upper() + ";tools", "docker_host": "remote"}, windows=True)
            self.assertEqual(child["PATH"].split(";").count(canonical), 1)
            self.assertEqual(len(child["PATH"].split(";")), 2)
            self.assertNotIn("docker_host", child)

    @unittest.skipIf(os.name == "nt", "POSIX path behavior")
    def test_linux_keeps_normal_path_separator_and_configuration(self):
        child = environment("/opt/docker/docker", {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": "/private/config"}, windows=False)
        self.assertEqual(child["PATH"], "/usr/bin:/bin")
        self.assertEqual(child["DOCKER_CONFIG"], "/private/config")

    @unittest.skipUnless(os.name == "nt", "Native Windows executable lookup")
    def test_native_windows_resolves_a_credential_helper_with_an_initially_missing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "Docker Desktop/resources/bin/docker.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            helper = binary.with_name("docker-credential-desktop.exe")
            helper.write_bytes(b"MZ")
            system = Path(os.environ["SystemRoot"]) / "System32"
            source = {key: value for key, value in os.environ.items() if key.upper() != "PATH"}
            source["PATH"] = str(system)
            source["PROGRAMFILES"] = str(Path(directory) / "uninstalled-programs")
            source["LOCALAPPDATA"] = str(Path(directory) / "empty-appdata")
            where = system / "where.exe"
            missing = subprocess.run([str(where), "docker-credential-desktop"], env=source, capture_output=True)
            self.assertNotEqual(missing.returncode, 0)
            with patch.dict(os.environ, source, clear=True):
                docker = Docker("desktop-linux")
                docker.executable = str(binary)
                found = subprocess.run([str(where), "docker-credential-desktop"], env=docker.environment(), capture_output=True, text=True)
            self.assertEqual(found.returncode, 0, found.stderr)
            self.assertEqual(Path(found.stdout.strip()).resolve(), helper.resolve())


if __name__ == "__main__":
    unittest.main()
