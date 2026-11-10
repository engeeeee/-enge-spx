import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from enge_spx.brand import CONTAINERS, DATA_DIRECTORY, LEGACY_DATA_DIRECTORY, LEGACY_LABEL_ROOT
from enge_spx.compat import LEGACY_RECIPES, LEGACY_BROWSER_TOKEN
from enge_spx.engine import Engine, OWNER, RECIPE
from enge_spx.state import Store, SPXError, atomic_json, default_home, fingerprint


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def legacy_store(self):
        home = self.base / LEGACY_DATA_DIRECTORY
        atomic_json(home / "instance.json", {"id": "123456789abc"})
        return Store(home)

    def test_fresh_install_uses_spx_data_and_resource_namespace(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.base)}):
            self.assertEqual(default_home(), self.base / DATA_DIRECTORY)
            store = Store()
        engine = Engine(store)
        self.assertFalse(store.legacy)
        self.assertTrue(engine.prefix.startswith("spx-"))
        self.assertEqual(engine.owner, OWNER)
        self.assertFalse(any(LEGACY_BROWSER_TOKEN in x for x in engine.proxy_env({"proxy": "http://proxy", "browser_token": "token"})))

    def test_existing_default_is_reused_without_moving_secrets(self):
        store = self.legacy_store()
        settings = {**store.settings(), "selected": "saved-node"}
        store.write("settings.json", settings)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.base)}):
            reopened = Store()
        self.assertEqual(reopened.home, store.home)
        self.assertEqual(reopened.instance, store.instance)
        self.assertEqual(reopened.settings(), settings)
        self.assertFalse((self.base / DATA_DIRECTORY).exists())

    def test_legacy_resources_remain_owned_and_new_resources_are_rejected(self):
        store = self.legacy_store()
        engine = Engine(store)
        self.assertEqual(engine.prefix, "ewbw-" + store.instance)
        engine.owned({"Config": {"Labels": {engine.owner: store.instance, engine.role: "project"}}}, "project")
        with self.assertRaises(SPXError):
            engine.owned({"Config": {"Labels": {OWNER: store.instance}}})

    def test_legacy_work_layers_are_reused_but_security_images_require_upgrade(self):
        store = self.legacy_store()
        engine = Engine(store)
        ids = {role: "sha256:" + str(i) * 64 for i, role in enumerate(LEGACY_RECIPES, 1)}
        images = {ids[role]: {"Id": ids[role], "Config": {"Labels": {LEGACY_LABEL_ROOT + ".recipe": value}}} for role, value in LEGACY_RECIPES.items()}
        for role in ("gateway", "browser"):
            self.assertFalse(engine.compatible_image(images[ids[role]], role))
            images[ids[role]]["Config"]["Labels"] = {RECIPE: engine.recipes[role]}
        store.write("images.json", ids)
        engine.doctor = Mock(return_value={"architecture": "amd64"})
        engine.networks = Mock()
        engine.docker = Mock()
        engine.docker.inspect.side_effect = lambda kind, identifier: images.get(identifier)
        with patch("enge_spx.downloads.manifest", side_effect=AssertionError("Unexpected download")):
            engine.install_prebuilt()
        engine.install()
        engine.docker.run.assert_not_called()
        self.assertEqual(engine.image_ids(), ids)
        self.assertEqual(engine.runtime_path("work", "probe.py"), "/opt/ewb/probe.py")
        self.assertEqual(store.read("images.json"), ids)

    def test_new_runtime_selects_spx_paths_and_unknown_recipe_is_rejected(self):
        engine = Engine(Store(self.base / "fresh"))
        ids = {role: "sha256:" + str(i) * 64 for i, role in enumerate(engine.recipes, 1)}
        engine.store.write("images.json", ids)
        images = {ids[role]: {"Id": ids[role], "Config": {"Labels": {RECIPE: value}}} for role, value in engine.recipes.items()}
        engine.docker = Mock()
        engine.docker.inspect.side_effect = lambda kind, identifier: images.get(identifier)
        self.assertEqual(engine.runtime_path("browser", "vnc_stdio.py"), "/opt/spx/vnc_stdio.py")
        images[ids["work"]]["Config"]["Labels"][RECIPE] = "unknown"
        with self.assertRaises(SPXError):
            engine.image_ids()

    def test_profile_migration_preserves_existing_cookies(self):
        spec = importlib.util.spec_from_file_location("spx_browser_migration", CONTAINERS / "browser.py")
        browser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(browser)
        old = self.base / ".config/chromium-ewb"
        old.mkdir(parents=True)
        (old / "Cookies.fixture").write_text("preserved")
        new = Path(browser.browser_profile(self.base))
        self.assertEqual((new / "Cookies.fixture").read_text(), "preserved")
        self.assertFalse(old.exists())
        self.assertEqual(browser.browser_profile(self.base), str(new))

    def test_stopped_pre_sandbox_browser_does_not_block_upgrade_confirmation(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                store = self.legacy_store() if legacy else Store(self.base / "fresh")
                engine = Engine(store)
                store.write("gateway/config.json", {"fixture": "configuration"})
                state = {"session": "session", "gateway": "gateway", "config_hash": fingerprint(store.read("gateway/config.json"))}
                def container(role, running=True):
                    networks = {engine.internal: {}}
                    if role == "gateway":
                        networks[engine.external] = {}
                    return {"Id": role, "State": {"Running": running}, "Config": {"Labels": {engine.owner: store.instance, engine.role: role}}, "NetworkSettings": {"Networks": networks}, "HostConfig": {"NetworkMode": "container:session", "Dns": ["127.0.0.1"]}}
                objects = {engine.prefix + "-" + role: container(role, role != "browser") for role in ("gateway", "session", "project", "browser")}
                # The old stopped browser intentionally has no readonly rootfs,
                # non-root image user, or application seccomp profile.
                old_browser = objects[engine.prefix + "-browser"]
                old_browser["Mounts"] = [{"Type": "volume", "Name": engine.prefix + "-browser-home", "Destination": "/home/workspace"}]
                engine.docker = Mock()
                def inspect(kind, name):
                    if kind == "network":
                        return {"Internal": name == engine.internal, "Driver": "bridge", "EnableIPv6": False, "Options": {"com.docker.network.bridge.gateway_mode_ipv4": "isolated"} if name == engine.internal else {}, "Labels": {engine.owner: store.instance}}
                    return objects.get(name) or next((item for item in objects.values() if item["Id"] == name), None)
                engine.docker.inspect.side_effect = inspect
                def run(*args, **kwargs):
                    self.assertEqual(args, ("rm", "browser"))
                    del objects[engine.prefix + "-browser"]
                    return "browser"
                engine.docker.run.side_effect = run
                engine.managed = lambda: list(objects)
                engine.doctor = Mock()
                engine._stop = Mock()
                engine.take_over_legacy_guard = Mock()
                engine.setup = Mock(return_value=state)
                engine.ensure_forward = Mock()
                engine.wait_line_listener = Mock()
                engine.policy = Mock(return_value="policy")
                engine.probe_chain = Mock(return_value={"ip": "203.0.113.1", "direct_blocked": True})
                engine.set_lease = Mock()
                engine.start_guard = Mock()
                engine.check()
                engine.confirm()
                self.assertEqual(store.read("runtime.json")["phase"], "ready")
                self.assertNotIn(engine.prefix + "-browser", objects)
                self.assertIn(engine.prefix + "-project", objects)
                engine.docker.run.assert_called_once_with("rm", "browser")

    def test_browser_retirement_refuses_foreign_ownership_and_never_forces_a_running_browser(self):
        store = Store(self.base / "fresh")
        engine = Engine(store)
        engine.docker = Mock()
        obj = {"Id": "running-browser", "State": {"Running": True}, "Config": {"Labels": {engine.owner: store.instance, engine.role: "browser"}}}
        engine.docker.inspect.return_value = obj
        self.assertEqual(engine._retire_stopped_browser(), obj)
        engine.docker.run.assert_not_called()
        # A running unsafe browser is still rejected by the unchanged audit.
        from enge_spx.browser_security import validate_container
        with self.assertRaises(SPXError):
            validate_container(obj)
        obj["State"]["Running"] = False
        obj["Config"]["Labels"][engine.owner] = "another-instance"
        with self.assertRaisesRegex(SPXError, "资源归属"):
            engine._retire_stopped_browser()
        engine.docker.run.assert_not_called()


    def test_legacy_guard_handoff_waits_for_the_previous_controller(self):
        store = self.legacy_store()
        store.write("runtime.json", {"phase": "ready"})
        held = threading.Event()
        def previous_guard():
            with store.lock("guard"):
                held.set()
                deadline = time.monotonic() + 3
                while store.read("runtime.json")["phase"] != "stopped" and time.monotonic() < deadline:
                    time.sleep(.01)
        thread = threading.Thread(target=previous_guard)
        thread.start()
        self.assertTrue(held.wait(2))
        store.write("runtime.json", {"phase": "stopped"})
        Engine(store).take_over_legacy_guard()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(store.read("controller.json"), {"app": "enge-spx"})

    def test_forward_heartbeat_does_not_replace_a_ready_guest_listener(self):
        store = Store(self.base / "fresh")
        state = {"gateway": "owned-gateway", "policy": "policy", "forward_target": {"host": "127.0.0.1", "port": 7890}}
        store.write("forward.json", {"gateway": state["gateway"], "policy": state["policy"], "heartbeat": time.time()})
        engine = Engine(store)
        engine.docker = Mock()
        engine.background = Mock()
        engine.docker.run.side_effect = [SPXError("listener not ready"), ""]
        with patch("enge_spx.engine.time.sleep"):
            engine.ensure_forward(state)
        self.assertEqual(engine.docker.run.call_count, 2)
        self.assertEqual(engine.docker.run.call_args.args[:2], ("exec", state["gateway"]))


if __name__ == "__main__":
    unittest.main()
