import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from enge_spx import storage
from enge_spx.engine import Engine, STORAGE
from enge_spx.state import SPXError, Store, atomic_json, default_home, fingerprint, location_file


class StorageCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "local"), "APPDATA": str(self.base / "roaming")})
        env.start()
        self.addCleanup(env.stop)
        self.store = Store()
        self.target = self.base / "目标 disk" / "ENGE SPX"

    def stop(self, *ignored):
        self.store.write("runtime.json", {"phase": "stopped"})
        self.store.write("gateway/lease.json", {"expires": 0})


class StorageTests(StorageCase):
    def test_move_preserves_identity_secrets_partial_downloads_and_explicit_shortcuts(self):
        settings = {**self.store.settings(), "terminal": {"kind": "pebrel", "executable": "D:/Pebrel/pebrel.exe"}, "selected": "saved"}
        self.store.write("settings.json", settings)
        self.store.write("nodes.json", [{"password": "private"}])
        cache = self.store.home / "cache/runtime.part"
        cache.parent.mkdir()
        cache.write_bytes(b"download" * 65536)
        old = self.store.home
        result = storage.migrate_home(self.store, self.target, self.stop)
        reopened = Store()
        self.assertEqual(reopened.home, self.target.resolve())
        self.assertEqual(reopened.instance, self.store.instance)
        self.assertEqual(reopened.settings(), settings)
        self.assertEqual(reopened.read("nodes.json"), [{"password": "private"}])
        self.assertEqual((reopened.home / "cache/runtime.part").read_bytes(), b"download" * 65536)
        self.assertEqual(reopened.read("runtime.json")["phase"], "stopped")
        self.assertEqual(Store(old).home, reopened.home)
        self.assertFalse(cache.exists())
        self.assertFalse((old / "nodes.json").exists())
        self.assertTrue((old / "relocated.json").is_file())
        self.assertFalse(result["leftovers"])
        for action in (lambda: self.store.write("settings.json", {}), lambda: self.store.lock().__enter__()):
            with self.assertRaises(SPXError):
                action()

    def test_multiple_moves_follow_old_data_paths(self):
        first = self.store.home
        storage.migrate_home(self.store, self.target, self.stop)
        second = Store()
        third = self.base / "third"
        storage.migrate_home(second, third, lambda: second.write("runtime.json", {"phase": "stopped"}))
        self.assertEqual(Store(first).home, third.resolve())
        self.assertEqual(Store().home, third.resolve())

    def test_unavailable_migrated_drive_does_not_create_an_empty_environment(self):
        atomic_json(location_file(), {"home": str(self.target), "instance": self.store.instance})
        with self.assertRaises(SPXError):
            Store()
        self.assertFalse(self.target.exists())

    def test_preflight_rejects_occupied_overlap_project_and_relative_paths(self):
        project = self.base / "project"
        project.mkdir()
        self.store.write("settings.json", {**self.store.settings(), "projects": [str(project)]})
        occupied = self.base / "occupied"
        occupied.mkdir()
        (occupied / "user.txt").write_text("keep")
        for value in (occupied, self.store.home, self.store.home / "nested", self.store.home.parent, project / "nested", "relative/path"):
            with self.subTest(value=value), self.assertRaises(SPXError):
                storage.plan_migration(self.store, value)
        self.assertEqual((occupied / "user.txt").read_text(), "keep")

    def test_low_space_rejected_before_stopping(self):
        with patch.object(storage.shutil, "disk_usage", return_value=Mock(free=1)):
            stop = Mock()
            with self.assertRaises(SPXError):
                storage.migrate_home(self.store, self.target, stop)
            stop.assert_not_called()

    def test_missing_drive_is_rejected_without_searching_forever(self):
        with patch.object(Path, "exists", return_value=False), self.assertRaises(SPXError):
            storage._parent(self.target)

    def test_bad_copy_keeps_source_and_default_pointer(self):
        self.store.write("nodes.json", [{"secret": "keep"}])
        old = self.store.home
        with patch.object(storage, "_digest", return_value="wrong digest"), self.assertRaises(SPXError):
            storage.migrate_home(self.store, self.target, self.stop)
        self.assertEqual(Store().home, old)
        self.assertEqual(self.store.read("nodes.json"), [{"secret": "keep"}])
        self.assertFalse((old / "relocated.json").exists())
        self.assertFalse(list(self.target.parent.glob("*.spx-moving-*")))

    def test_source_change_during_copy_aborts_activation(self):
        payload = self.store.home / "large-file"
        payload.write_bytes(b"x" * (2 * 1024**2))
        def progress(value):
            if value["stage"] == "copy":
                payload.write_bytes(b"changed")
        with self.assertRaises(SPXError):
            storage.migrate_home(self.store, self.target, self.stop, progress)
        self.assertEqual(payload.read_bytes(), b"changed")
        self.assertFalse(location_file().exists())

    def test_migration_waits_for_background_locks_and_times_out_safely(self):
        with self.store.lock("guard"):
            with self.assertRaises(SPXError):
                storage.migrate_home(self.store, self.target, self.stop, wait_seconds=0)
        self.assertFalse(self.target.exists())
        self.assertEqual(default_home().resolve(), self.store.home)
        held = threading.Event()
        self.store.write("runtime.json", {"phase": "ready"})
        def guard():
            with self.store.lock("guard"):
                held.set()
                while self.store.read("runtime.json")["phase"] == "ready":
                    time.sleep(.01)
        thread = threading.Thread(target=guard)
        thread.start()
        self.assertTrue(held.wait(2))
        storage.migrate_home(self.store, self.target, self.stop)
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_cleanup_failure_keeps_verified_new_directory_active(self):
        payload = self.store.home / "cache.tar.gz"
        payload.write_bytes(b"verified")
        original = storage._digest
        def digest(path):
            if path == payload:
                raise PermissionError("locked by another process")
            return original(path)
        with patch.object(storage, "_digest", side_effect=digest):
            result = storage.migrate_home(self.store, self.target, self.stop)
        self.assertTrue(result["leftovers"])
        self.assertEqual(Store().home, self.target.resolve())
        self.assertEqual((self.target / payload.name).read_bytes(), b"verified")

    @unittest.skipUnless(os.name == "nt", "native Windows drive relocation")
    def test_migrate_to_another_windows_drive(self):
        workspace = os.environ.get("GITHUB_WORKSPACE")
        if not workspace or Path(workspace).drive.lower() == self.store.home.drive.lower():
            self.skipTest("a second writable drive is not available")
        payload = self.store.home / "partial-download.part"
        payload.write_bytes(b"cross-drive fixture" * 4096)
        expected = payload.read_bytes()
        with tempfile.TemporaryDirectory(prefix="spx-drive-test-", dir=workspace) as temporary:
            target = Path(temporary) / "移植 data"
            storage.migrate_home(self.store, target, self.stop)
            reopened = Store()
            self.assertNotEqual(reopened.home.drive.lower(), self.store.home.drive.lower())
            self.assertEqual(reopened.instance, self.store.instance)
            self.assertEqual((reopened.home / payload.name).read_bytes(), expected)
            self.assertFalse(payload.exists())

    def test_bootstrap_failure_can_still_follow_original_location(self):
        original = storage.atomic_json
        def write(path, value):
            if path == location_file():
                raise PermissionError("bootstrap read only")
            return original(path, value)
        with patch.object(storage, "atomic_json", side_effect=write):
            result = storage.migrate_home(self.store, self.target, self.stop)
        self.assertTrue(result["leftovers"])
        self.assertEqual(Store().home, self.target.resolve())

    @unittest.skipUnless(os.name != "nt", "Windows junction coverage uses filesystem validation in native migration")
    def test_links_cannot_copy_unrelated_files(self):
        secret = self.base / "unrelated"
        secret.write_text("keep")
        (self.store.home / "link").symlink_to(secret)
        with self.assertRaises(SPXError):
            storage.plan_migration(self.store, self.target)
        self.assertEqual(secret.read_text(), "keep")

    def test_gateway_is_recreated_for_new_home_but_project_layer_is_reused(self):
        engine = Engine(self.store)
        old = {"Image": "same", "Id": "old", "State": {"Running": False}, "Config": {"Labels": {}}}
        new = {"Id": "new"}
        engine.inspect = Mock(side_effect=[old, new])
        engine.docker = Mock()
        self.assertEqual(engine.ensure_container("gateway", "same", []), new)
        self.assertEqual(engine.docker.run.call_args_list[0].args, ("rm", "old"))
        self.assertIn(STORAGE + "=" + fingerprint(os.path.normcase(str(self.store.home)))[:24], engine.docker.run.call_args.args)
        engine.inspect = Mock(side_effect=[old, old])
        engine.docker.reset_mock()
        engine.ensure_container("project", "same", [])
        engine.docker.run.assert_called_once_with("start", engine.prefix + "-project")


class DockerMoveTests(StorageCase):
    def desktop_settings(self, folder):
        path = self.base / "roaming/Docker/settings-store.json"
        atomic_json(path, {"dataFolder": str(folder), "unrelated": "preserve"})
        disk = folder / "wsl/disk/docker_data.vhdx"
        disk.parent.mkdir(parents=True, exist_ok=True)
        disk.write_bytes(b"disk fixture")
        return path

    def engine(self):
        engine = Engine(self.store)
        engine.doctor = Mock(return_value={})
        engine._stop = Mock(side_effect=self.stop)
        engine.managed = Mock(return_value=["container-id"])
        engine.docker = Mock(context="desktop-linux")
        engine.docker.run.side_effect = lambda *args: engine.prefix + "-tools-home\nother-volume" if args[:2] == ("volume", "ls") else "other-container"
        engine.docker.inspect.return_value = {"Config": {"Labels": {engine.owner: self.store.instance}}}
        return engine

    def test_prepare_only_records_a_plan_and_never_moves_or_edits_docker_disk(self):
        previous = self.base / "original docker"
        settings = self.desktop_settings(previous)
        before = settings.read_bytes()
        engine = self.engine()
        result = storage.prepare_docker_move(engine, self.target)
        self.assertEqual(result["phase"], "prepared")
        self.assertEqual(result["volumes"], [engine.prefix + "-tools-home"])
        self.assertEqual(result["other_running"], 1)
        self.assertTrue((previous / "wsl/disk/docker_data.vhdx").is_file())
        self.assertEqual(settings.read_bytes(), before)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse(any(call.args[0] in ("rm", "prune", "kill", "stop") for call in engine.docker.run.call_args_list))

    def test_verification_requires_resources_and_actual_target_location(self):
        engine = self.engine()
        self.desktop_settings(self.base / "original docker")
        storage.prepare_docker_move(engine, self.target)
        with self.assertRaises(SPXError):
            storage.verify_docker_move(engine)
        self.desktop_settings(self.target)
        result = storage.verify_docker_move(engine)
        self.assertEqual(result["phase"], "verified")
        engine.docker.inspect.side_effect = lambda kind, identifier: None if kind == "volume" else {"Config": {"Labels": {engine.owner: self.store.instance}}}
        with self.assertRaises(SPXError):
            storage.verify_docker_move(engine)


if __name__ == "__main__":
    unittest.main()
