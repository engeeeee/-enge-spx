from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from enge_spx.engine import Engine
from enge_spx.resource_limits import NORMAL, arguments, budget, preset, validate
from enge_spx.state import SPXError, Store


class BudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "data")
        self.engine = Engine(self.store)

    def test_missing_config_preserves_old_budgets_without_writing_settings(self):
        self.assertNotIn("resources", self.store.settings())
        config = validate()
        self.assertEqual(config["budgets"], NORMAL)
        self.assertTrue(config["auto_browser"])
        self.assertEqual(arguments(budget(config, "gateway")), [])
        self.assertIn(str(4 * 1024**3), arguments(budget(config, "project")))
        self.assertFalse((self.store.home / "settings.json").exists())

    def test_low_preset_and_independent_project_budget_are_not_shared(self):
        config = preset("low")
        self.assertFalse(config["auto_browser"])
        key = "a" * 16
        config["projects"][key] = {"cpus": .29, "memory_mb": 768}
        normalized = validate(config)
        self.assertEqual(budget(normalized, "project", key), {"cpus": .29, "memory_mb": 768})
        self.assertEqual(budget(normalized, "project", "b" * 16)["memory_mb"], 2048)
        self.assertEqual(budget(preset(), "project")["memory_mb"], 4096)
        self.assertEqual(arguments({"cpus": 0, "memory_mb": 0}, update=True)[-1], "-1")

    def test_unknown_schema_keys_unsafe_limits_and_invalid_project_ids_reject(self):
        variants = []
        for key, value in (("schema", 2), ("schema", True), ("auto_browser", "false"), ("mode", "direct"), ("projects", {"../escape": {"cpus": 1, "memory_mb": 1024}}), ("unexpected", True)):
            config = preset(); config[key] = value; variants.append(config)
        for field, values in (("cpus", (True, -.25, .1, 129, float("nan"), float("inf"), 1.234, 10**1000)), ("memory_mb", (True, -1, .5, 511, 131073))):
            for value in values:
                config = preset(); config["budgets"]["project"][field] = value; variants.append(config)
        for config in variants:
            with self.subTest(config=str(config)[:80]), self.assertRaises(SPXError):
                validate(config)

    def test_save_and_undo_stop_only_when_changed_and_preserve_old_settings(self):
        original = {**self.store.settings(), "selected": "old-node", "projects": ["saved-project"], "unrelated": {"keep": True}}
        self.store.write("settings.json", original)
        self.engine._stop = Mock()
        self.engine.save_resources(preset("low"))
        self.engine._stop.assert_called_once()
        self.assertEqual(self.store.settings()["unrelated"], {"keep": True})
        backup = self.store.read("resources-previous.json")
        self.engine.save_resources(preset("low"))
        self.assertEqual(self.engine._stop.call_count, 1)
        self.assertEqual(self.store.read("resources-previous.json"), backup)
        self.engine.restore_resources()
        self.assertEqual(self.store.settings()["resources"], preset())
        self.assertEqual(self.store.settings()["projects"], ["saved-project"])
        self.assertEqual(self.store.settings()["selected"], "old-node")
        self.assertEqual(set(json.loads((self.store.home / "resources-previous.json").read_text())), {"schema", "resources"})

    def existing(self, running=False):
        self.store.write("settings.json", {**self.store.settings(), "resources": preset("low")})
        engine = self.engine
        obj = {"Id": "original-id", "Image": "image", "Config": {"Labels": {engine.owner: self.store.instance, engine.role: "project"}}, "State": {"Running": running}, "HostConfig": {"Memory": 4 * 1024**3, "CpuQuota": 0, "CpuPeriod": 0}}
        engine.docker = Mock()
        engine.docker.inspect.return_value = obj
        def execute(*args, **kwargs):
            if args[0] == "update":
                obj["HostConfig"].update(Memory=int(args[args.index("--memory") + 1]), CpuPeriod=int(args[args.index("--cpu-period") + 1]), CpuQuota=int(args[args.index("--cpu-quota") + 1]))
            elif args[0] == "start":
                obj["State"]["Running"] = True
            else:
                self.fail("Resource changes must not create/remove a container")
            return ""
        engine.docker.run.side_effect = execute
        return obj

    def test_stopped_update_precedes_start_and_preserves_container_identity(self):
        obj = self.existing()
        result = self.engine.ensure_container("project", "image", [])
        self.assertEqual(result["Id"], "original-id")
        self.assertEqual(obj["HostConfig"]["Memory"], 2 * 1024**3)
        self.assertEqual([call.args[0] for call in self.engine.docker.run.call_args_list], ["update", "start"])
        self.assertFalse(any("privileged" in str(call) or "seccomp" in str(call) for call in self.engine.docker.run.call_args_list))

    def test_update_failure_and_changed_running_budget_never_start_or_remove(self):
        for running in (False, True):
            with self.subTest(running=running):
                obj = self.existing(running)
                self.engine.docker.run.side_effect = SPXError("resource rejected")
                with self.assertRaises(SPXError):
                    self.engine.ensure_container("project", "image", [])
                self.assertEqual(obj["State"]["Running"], running)
                self.assertTrue(all(call.args[0] == "update" for call in self.engine.docker.run.call_args_list))

    def test_per_project_override_reaches_actual_creation_arguments(self):
        path = self.store.home.parent / "project"
        path.mkdir()
        _, key = self.store.project(str(path))
        config = preset("low")
        config["projects"][key] = {"cpus": .5, "memory_mb": 768}
        self.store.write("settings.json", {**self.store.settings(), "resources": config})
        self.engine.image_ids = Mock(return_value={"work": "image"})
        self.engine.ensure_container = Mock(return_value={"Id": "kept", "Name": self.engine.prefix + "-project-" + key, "Config": {"User": "1000:1000", "Labels": {self.engine.role: "project"}}, "State": {"Running": True}, "HostConfig": {"Privileged": False, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"]}, "Mounts": [{"Type": "volume", "Name": self.engine.prefix + "-tools-home", "Destination": "/home/workspace", "RW": True}, {"Type": "bind", "Source": str(path), "Destination": "/workspace/" + key, "RW": True}]})
        self.engine.proxy_env = Mock(return_value=[])
        with patch('enge_spx.workspace_timezone.prepare_project'):
            self.engine._project(str(path), {"session": "network-session"})
        self.assertEqual(self.engine.ensure_container.call_args.kwargs["resource_key"], key)
        with patch.object(self.store, "write") as write, patch('enge_spx.workspace_timezone.prepare_project'):
            self.engine._project(str(path), {"session": "network-session"})
            write.assert_not_called()

    def test_browser_stop_preserves_ready_cli_and_profile_and_still_stops_on_write_denial(self):
        self.store.write("runtime.json", {"phase": "ready", "session": "existing"})
        browser = {"Id": "owned-browser", "State": {"Running": True}}
        self.engine.inspect = Mock(return_value=browser)
        self.engine.docker = Mock()
        self.engine._quiesce_browser = Mock()
        result = self.engine.stop_browser()
        self.engine._quiesce_browser.assert_called_once_with(browser)
        self.assertTrue(result["workspace_kept"])
        self.engine.docker.run.assert_called_once_with("stop", "--time", "8", "owned-browser", timeout=25)
        self.assertEqual(self.store.read("runtime.json")["phase"], "ready")
        self.assertEqual(self.store.read("browser-state.json")["phase"], "stopped")
        self.engine.docker.run.reset_mock()
        with patch.object(self.store, "write", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.engine.stop_browser()
        self.engine.docker.run.assert_called_once()

    def test_auto_browser_off_keeps_cli_sandbox_choice_and_explicit_override(self):
        config = preset("low")
        self.store.write("settings.json", {**self.store.settings(), "resources": config})
        engine = self.engine
        engine.ready = Mock(return_value={"session": "session", "browser_token": "synthetic"})
        engine._browser = Mock(return_value="http://127.0.0.1/viewer")
        engine._project = Mock(return_value=({"Id": "project"}, "key"))
        engine.proxy_env = Mock(return_value=[])
        engine.control_env = Mock(return_value=[])
        engine.docker.command = Mock(return_value=["docker", "exec"])
        path = self.store.home.parent / "fixture"
        path.mkdir()
        engine.tool_command(str(path), ["codex"])
        engine._browser.assert_not_called()
        engine.tool_command(str(path), ["claude"], browser=True)
        engine._browser.assert_called_once()
        engine._browser.reset_mock()
        engine.tool_command(str(path), ["claude"], browser=False)
        engine._browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
