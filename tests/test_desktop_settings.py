import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from enge_spx import desktop_settings as settings


class DesktopSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.roaming = self.base / "roaming/Docker"
        self.common = self.base / "common/DockerDesktop"
        self.roaming.mkdir(parents=True)
        self.common.mkdir(parents=True)
        environment = patch.dict(os.environ, {"APPDATA": str(self.roaming.parent), "ProgramData": str(self.common.parent)})
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, data, filename="settings-store.json", machine=False):
        path = (self.common if machine else self.roaming) / filename
        path.write_text(json.dumps(data), encoding="utf-8-sig")
        return path

    def test_sparse_current_settings_and_empty_default_require_wsl2_registration(self):
        for data in ({}, {"SettingsVersion": 42, "AutoStart": False, "private-not-reported": "synthetic-secret"}):
            with self.subTest(data_keys=list(data)):
                path = self.write(data)
                before = path.read_bytes()
                result = settings.configuration()
                self.assertEqual(result, settings.Backend(True, "default_wsl2", True))
                self.assertEqual(path.read_bytes(), before)
                self.assertNotIn("synthetic-secret", repr(result))

    def test_explicit_flat_pascal_grouped_and_wrapped_values_preserve_selection(self):
        for data in ({"wslEngineEnabled": True}, {"WslEngineEnabled": True}, {"wslEngineEnabled": {"value": True}}, {"linuxVM": {"wslEngineEnabled": {"value": True}}}):
            self.write(data)
            self.assertEqual(settings.configuration(), settings.Backend(True, "explicit_user"))
        for data in ({"wslEngineEnabled": False}, {"WslEngineEnabled": {"value": False}}):
            self.write(data)
            self.assertEqual(settings.configuration().reason, "user_disabled")
            self.assertFalse(settings.configuration().enabled)

    def test_policy_priority_and_installer_override_are_resolved_without_edits(self):
        self.write({"wslEngineEnabled": True})
        self.write({"wslEngineEnabled": False, "backend": "hyper-v"}, "install-settings.json", True)
        self.write({"linuxVM": {"wslEngineEnabled": {"value": False, "locked": False}}}, "admin-settings.json", True)
        self.assertEqual(settings.configuration().reason, "explicit_user")
        self.write({"linuxVM": {"wslEngineEnabled": {"value": False, "locked": True}}}, "admin-settings.json", True)
        self.assertEqual(settings.configuration(), settings.Backend(False, "conflicting_policy"))
        self.write({"wslEngineEnabled": False})
        self.write({"linuxVM": {"wslEngineEnabled": {"value": True, "locked": True}}}, "admin-settings.json", True)
        self.assertEqual(settings.configuration(), settings.Backend(False, "conflicting_policy"))
        self.write({})
        self.assertEqual(settings.configuration(), settings.Backend(False, "conflicting_policy"))
        (self.common / "install-settings.json").unlink()
        self.assertEqual(settings.configuration(), settings.Backend(True, "locked_policy", True))

    def test_implicit_selection_honors_machine_and_non_wsl_backends(self):
        for machine, expected in (({"wslEngineEnabled": False}, "install_disabled"), ({"backend": "hyper-v"}, "other_install_backend"), ({"backend": "docker-vmm"}, "other_install_backend"), ({"backend": "wsl-2"}, "install_backend_wsl2")):
            self.write({})
            self.write(machine, "install-settings.json", True)
            result = settings.configuration()
            self.assertEqual(result.reason, expected)
            self.assertEqual(result.enabled, expected == "install_backend_wsl2")
        for data in ({"useWindowsContainers": True}, {"UseDockerVMM": True}, {"virtualMachineManager": "docker-vmm"}, {"wslEngineEnabled": True, "backend": "hyper-v"}):
            self.write(data)
            self.assertEqual(settings.configuration(), settings.Backend(False, "other_backend_selected"))

    def test_missing_or_unreadable_settings_are_distinct_and_never_defaults(self):
        self.assertEqual(settings.configuration(), settings.Backend(False, "user_settings_missing"))
        self.write({})
        with patch.object(settings, "_read", side_effect=PermissionError("private-user-path")):
            self.assertEqual(settings.configuration(), settings.Backend(False, "user_settings_denied"))
        with patch.object(settings, "_folder", return_value=None):
            self.assertEqual(settings.configuration(), settings.Backend(False, "profile_directory_unavailable"))

    def test_current_invalid_conflicting_or_oversized_data_never_uses_stale_legacy(self):
        self.write({"wslEngineEnabled": True}, "settings.json")
        path = self.roaming / "settings-store.json"
        fixtures = ['[]', 'null', '{', '{"unrelated":NaN}', '{"wslEngineEnabled":"true"}', '{"wslEngineEnabled":1}', '{"wslEngineEnabled":true,"WslEngineEnabled":false}', '{"wslEngineEnabled":true,"wslEngineEnabled":false}', '{"wslEngineEnabled":{"value":true,"locked":"true"}}', '{"linuxVM":false}', ' ' * (1024 * 1024 + 1)]
        for raw in fixtures:
            with self.subTest(length=len(raw)):
                path.write_text(raw)
                self.assertFalse(settings.configuration().enabled)
        path.unlink()
        self.assertEqual(settings.configuration(), settings.Backend(True, "explicit_user"))

    def test_corrupt_machine_files_cannot_fall_back_to_documented_default(self):
        self.write({})
        for name, code in (("admin-settings.json", "admin_settings_unavailable"), ("install-settings.json", "install_settings_unavailable")):
            path = self.common / name
            path.write_text("private-not-json")
            self.assertEqual(settings.configuration(), settings.Backend(False, code))
            path.unlink()

    @unittest.skipUnless(os.name == "nt", "Native Windows current-user folder lookup")
    def test_native_folder_fallback_uses_current_profile_without_environment(self):
        with patch.dict(os.environ, {"APPDATA": "", "ProgramData": ""}):
            roaming = settings._folder("APPDATA", 26)
            common = settings._folder("ProgramData", 35)
        self.assertTrue(roaming.is_absolute() and roaming.is_dir())
        self.assertTrue(common.is_absolute() and common.is_dir())


if __name__ == "__main__":
    unittest.main()
