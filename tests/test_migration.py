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
from enge_spx.state import Store, SPXError, atomic_json, default_home


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

    def test_legacy_images_and_project_layers_are_reused_by_both_installers(self):
        store = self.legacy_store()
        engine = Engine(store)
        ids = {role: "sha256:" + str(i) * 64 for i, role in enumerate(LEGACY_RECIPES, 1)}
        images = {ids[role]: {"Id": ids[role], "Config": {"Labels": {LEGACY_LABEL_ROOT + ".recipe": value}}} for role, value in LEGACY_RECIPES.items()}
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
