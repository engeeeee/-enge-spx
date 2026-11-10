import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from enge_spx.engine import Engine
from enge_spx.state import Store, SPXError
from enge_spx import workspace_profiles as profiles


class WorkspaceProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.directory = self.root / "项目 with spaces"
        self.directory.mkdir()
        self.key = self.store.project(str(self.directory))[1]
        self.engine = Engine(self.store)
        self.engine.docker.executable = None

    def identity(self, name="独立身份"):
        return self.engine.create_workspace_profile(name)["profile"]

    def container(self, identity=profiles.SHARED, access="rw", running=False):
        volumes = profiles.volumes(self.engine, identity)
        target = "/workspace/" + self.key
        return {"Id": "fixture-project", "Image": "fixture-image", "Name": "/" + profiles.project_name(self.engine, identity, self.key, access), "Config": {"User": "1000:1000", "Labels": {self.engine.owner: self.store.instance, self.engine.role: "project", profiles.PROFILE: identity, profiles.PROJECT: self.key, profiles.ACCESS: access}}, "State": {"Running": running}, "HostConfig": {"Privileged": False, "CapAdd": [], "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges=true"], "NetworkMode": "container:session", "Mounts": [{"Type": "bind", "Source": str(self.directory), "Target": target, "ReadOnly": access == "ro", "BindOptions": {"ReadOnlyForceRecursive": access == "ro"}}]}, "Mounts": [{"Type": "volume", "Name": volumes["tools-home"], "Destination": "/home/workspace", "RW": True}, {"Type": "bind", "Source": str(self.directory), "Destination": target, "RW": access == "rw"}]}

    def test_absent_configuration_preserves_all_legacy_names_without_writes(self):
        before = set(self.store.home.iterdir())
        config = self.engine.workspace_profiles()
        plan = profiles.project_plan(self.engine, str(self.directory))
        self.assertEqual(config["selected"], "shared")
        self.assertEqual(plan["name"], self.engine.prefix + "-project-" + self.key)
        self.assertEqual(plan["access"], "rw")
        self.assertEqual(profiles.volumes(self.engine, "shared")["tools-home"], self.engine.prefix + "-tools-home")
        self.assertEqual(set(self.store.home.iterdir()), before)

    def test_unknown_null_and_incomplete_schemas_never_become_shared_accounts(self):
        for value in (None, {}, [], {**profiles.defaults(), "schema": True}, {**profiles.defaults(), "schema": 2}, {**profiles.defaults(), "unexpected": "value"}, {**profiles.defaults(), "selected": []}, {**profiles.defaults(), "projects": {"a" * 16: {"profile": "unknown", "access": "rw"}}}):
            with self.subTest(value=value):
                self.store.write(profiles.FILE, value)
                with self.assertRaises(SPXError):
                    self.engine.workspace_profiles()

    def test_initialized_marker_detects_missing_file_and_boolean_schema(self):
        self.identity()
        (self.store.home / profiles.FILE).unlink()
        with self.assertRaisesRegex(SPXError, "丢失"):
            self.engine.workspace_profiles()
        for marker in ({"schema": True, "enabled": True}, {"schema": 1, "enabled": 1}):
            self.store.write(profiles.MARKER, marker)
            with self.assertRaises(SPXError):
                self.engine.workspace_profiles()

    def test_oversized_or_redirected_identity_files_reject_before_parsing(self):
        path = self.store.home / profiles.FILE
        path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(SPXError):
            self.engine.workspace_profiles()
        path.unlink()
        original = self.root / "identity-original.json"
        original.write_text('{}')
        os.link(original, path)
        with self.assertRaises(SPXError):
            self.engine.workspace_profiles()

    def test_create_stays_shared_and_never_copies_or_stops_accounts(self):
        self.engine._shutdown_locked = Mock()
        first, second = self.identity("身份 A"), self.identity("身份 B")
        self.assertNotEqual(first, second)
        self.assertEqual(self.engine.workspace_profiles()["selected"], "shared")
        self.engine._shutdown_locked.assert_not_called()
        self.assertTrue(set(profiles.volumes(self.engine, first).values()).isdisjoint(profiles.volumes(self.engine, second).values()))
        self.assertTrue(set(profiles.volumes(self.engine, first).values()).isdisjoint(profiles.volumes(self.engine, "shared").values()))
        self.assertNotIn("password", (self.store.home / profiles.FILE).read_text())

    def test_invalid_duplicate_and_injected_names_do_not_change_configuration(self):
        self.identity("Account")
        before = self.store.read(profiles.FILE)
        for name in ("", "a" * 65, "fake\nname", "socks5://user:password@example/", "account"):
            with self.subTest(name=name):
                with self.assertRaises(SPXError):
                    self.identity(name)
        self.assertEqual(self.store.read(profiles.FILE), before)

    def test_switch_and_binding_require_verified_stop_before_persisting(self):
        identity = self.identity()
        self.engine._shutdown_locked = Mock(side_effect=SPXError("stop denied"))
        before = self.store.read(profiles.FILE)
        with self.assertRaises(SPXError):
            self.engine.configure_workspace(identity, str(self.directory), "ro")
        self.assertEqual(self.store.read(profiles.FILE), before)
        self.engine._shutdown_locked.side_effect = None
        result = self.engine.configure_workspace(identity, str(self.directory), "ro")
        self.assertEqual(result["selected"], identity)
        self.assertEqual(result["projects"][self.key], {"profile": identity, "access": "ro"})
        self.engine._shutdown_locked.assert_called()
        self.assertEqual(self.store.read(profiles.PREVIOUS)["config"], before)

    def test_invalid_profile_or_directory_rejects_before_stopping(self):
        self.engine._shutdown_locked = Mock()
        for identity, path, access in (("../escape", str(self.directory), "rw"), ("b" * 12, str(self.directory), "ro"), ("shared", str(self.directory), "write"), ("shared", str(self.store.home), "rw")):
            with self.subTest(identity=identity):
                with self.assertRaises((SPXError, OSError)):
                    self.engine.configure_workspace(identity, path, access)
        self.engine._shutdown_locked.assert_not_called()

    def test_policy_changes_only_for_selected_identity_or_project_grant(self):
        self.engine.node = Mock(return_value={"outbound": {"type": "socks", "server": "192.0.2.1", "server_port": 9}})
        original = self.engine.policy()
        identity = self.identity()
        self.assertEqual(self.engine.policy(), original)
        self.engine.configure_workspace(identity, str(self.directory), "ro")
        self.assertNotEqual(self.engine.policy(), original)

    def test_restore_keeps_all_created_identity_data_references(self):
        first = self.identity("A")
        self.engine.configure_workspace(first, str(self.directory), "ro")
        second = self.identity("B")
        self.engine.configure_workspace(second, str(self.directory), "rw")
        self.engine.restore_workspace_profiles()
        result = self.engine.workspace_profiles()
        self.assertEqual(result["selected"], first)
        self.assertEqual(result["projects"][self.key]["access"], "ro")
        self.assertIn(second, result["profiles"])

    def test_explicit_restore_recovers_missing_config_but_does_not_auto_fallback(self):
        identity = self.identity()
        self.engine.configure_workspace(identity, str(self.directory), "ro")
        (self.store.home / profiles.FILE).unlink()
        with self.assertRaises(SPXError):
            profiles.load(self.store)
        self.engine.restore_workspace_profiles()
        self.assertEqual(self.engine.workspace_profiles()["selected"], "shared")
        self.assertTrue((self.store.home / profiles.MARKER).is_file())

    def test_unbound_project_never_inherits_an_isolated_identity(self):
        identity = self.identity()
        self.engine.configure_workspace(identity)
        self.engine.ready = Mock()
        self.engine._browser = Mock()
        with self.assertRaisesRegex(SPXError, "尚未绑定"):
            self.engine.tool_command(str(self.directory), ["claude"])
        self.engine.ready.assert_not_called()
        self.engine._browser.assert_not_called()

    def test_readonly_has_distinct_container_and_strict_recursive_mount(self):
        rw = profiles.project_plan(self.engine, str(self.directory))
        self.engine.configure_workspace("shared", str(self.directory), "ro")
        ro = profiles.project_plan(self.engine, str(self.directory))
        self.assertNotEqual(ro["name"], rw["name"])
        self.assertIn("readonly,bind-recursive=readonly", " ".join(profiles.project_arguments(ro)))
        profiles.validate_mounts(self.engine, self.container(access="ro"), plan=ro)
        for field, value in (("ReadOnly", False), ("BindOptions", {})):
            obj = self.container(access="ro")
            obj["HostConfig"]["Mounts"][0][field] = value
            with self.assertRaises(SPXError):
                profiles.validate_mounts(self.engine, obj, plan=ro)

    def test_foreign_volume_extra_mount_and_wrong_project_source_reject(self):
        mutations = (
            lambda obj: obj["Mounts"][0].update(Name="foreign-tools-home"),
            lambda obj: obj["Mounts"].append({"Type": "bind", "Source": "/", "Destination": "/host", "RW": True}),
            lambda obj: obj["Mounts"][1].update(Source=str(self.directory.parent)),
            lambda obj: obj["HostConfig"].update(Privileged=True),
        )
        plan = profiles.project_plan(self.engine, str(self.directory))
        for mutate in mutations:
            obj = self.container()
            mutate(obj)
            with self.assertRaises(SPXError):
                profiles.validate_mounts(self.engine, obj, plan=plan)

    def test_existing_wrong_account_volume_is_rejected_before_start(self):
        obj = self.container()
        obj["Mounts"][0]["Name"] = "another-identity-tools-home"
        self.engine.docker = Mock(executable=None)
        self.engine.docker.inspect.return_value = obj
        self.engine.image_ids = Mock(return_value={"work": "fixture-image"})
        self.engine.proxy_env = Mock(return_value=[])
        self.engine._stop = Mock()
        with self.assertRaises(SPXError):
            self.engine._project(str(self.directory), {"session": "session"})
        self.engine.docker.run.assert_not_called()
        self.engine._stop.assert_called_once()

    def test_windows_drive_mapping_matches_exact_path_and_never_a_suffix(self):
        for actual in ("D:\\Projects\\demo", "/run/desktop/mnt/host/d/Projects/demo", "/host_mnt/d/Projects/demo"):
            self.assertTrue(profiles.same_source(actual, "D:\\Projects\\demo"))
        for actual in ("/host_mnt/c/Projects/demo", "/other/d/Projects/demo", "/host_mnt/d/Projects/demo-extra", "/host_mnt/d/Projects/another/demo"):
            self.assertFalse(profiles.same_source(actual, "D:\\Projects\\demo"))

    def test_browser_home_and_downloads_are_checked_for_cross_identity_mounts(self):
        identity = self.identity()
        self.engine.configure_workspace(identity)
        data = profiles.volumes(self.engine, identity)
        obj = {"Config": {"Labels": {self.engine.role: "browser", profiles.PROFILE: identity}}, "State": {"Running": True}, "Mounts": [{"Type": "volume", "Name": data["browser-home"], "Destination": "/home/workspace", "RW": True}, {"Type": "volume", "Name": data["downloads"], "Destination": "/home/workspace/Downloads", "RW": True}]}
        profiles.validate_mounts(self.engine, obj)
        obj["Mounts"][0]["Name"] = self.engine.prefix + "-browser-home"
        with self.assertRaises(SPXError):
            profiles.validate_mounts(self.engine, obj)

    def test_running_other_identity_and_stale_gui_choice_never_open_tools(self):
        identity = self.identity()
        self.engine.configure_workspace(identity, str(self.directory), "ro")
        with self.assertRaises(SPXError):
            profiles.validate_mounts(self.engine, self.container(running=True))
        self.engine.ready = Mock()
        self.engine._browser = Mock()
        with self.assertRaises(SPXError):
            self.engine._tool_session(str(self.directory), ["codex"], expected_workspace=("shared", "rw"))
        self.engine.ready.assert_not_called()
        self.engine._browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
