import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from enge_spx.credentials import CredentialCodec, DPAPI, FORMAT
from enge_spx.state import SPXError, Store, atomic_json


class MemoryProtector:
    """Opaque test handles; not a production cipher or a platform fallback."""
    def __init__(self):
        self.records = {}

    def protect(self, data, entropy):
        handle = secrets.token_bytes(32)
        self.records[handle] = (data, entropy)
        return handle

    def unprotect(self, data, entropy):
        if data not in self.records or self.records[data][1] != entropy:
            raise SPXError("wrong user, purpose or ciphertext")
        return self.records[data][0]


class CredentialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "private")
        self.backend = MemoryProtector()
        self.store.credentials = CredentialCodec(self.store.instance, self.backend)

    def test_sensitive_files_are_opaque_and_original_shapes_survive(self):
        values = {"nodes.json": [{"id": "unchanged", "outbound": {"password": "secret-node", "uuid": "private-uuid"}}], "settings.json": {"selected": "unchanged", "relay": {"url": "http://user:private@127.0.0.1:1080"}}, "gateway/config.json": {"outbounds": [{"password": "secret-node"}]}, "runtime.json": {"phase": "ready", "browser_token": "private-token"}, "relay.json": {"control": "private-control"}}
        for name, value in values.items():
            with self.subTest(name=name):
                self.store.write(name, value)
                raw = (self.store.home / name).read_text()
                self.assertNotIn("secret-node", raw)
                self.assertNotIn("private", raw)
                self.assertEqual(json.loads(raw)["format"], FORMAT)
                self.assertEqual(self.store.read(name), value)

    def test_swapped_purpose_or_installation_fails_instead_of_resetting(self):
        self.store.write("nodes.json", [{"password": "sensitive"}])
        envelope = json.loads((self.store.home / "nodes.json").read_text())
        for codec, name in ((self.store.credentials, "settings.json"), (CredentialCodec("different-id", self.backend), "nodes.json")):
            with self.assertRaises(SPXError):
                codec.decode(name, envelope)
        self.assertEqual(self.store.read("nodes.json"), [{"password": "sensitive"}])

    def test_old_plaintext_migrates_without_changing_ids_or_selected_node(self):
        node = [{"id": "original-id", "password": "original-secret"}]
        atomic_json(self.store.home / "nodes.json", node)
        atomic_json(self.store.home / "settings.json", {"selected": "original-id"})
        with patch("enge_spx.storage._private_directory"):
            result = self.store.migrate_credentials()
        self.assertTrue(result["encrypted"])
        self.assertEqual(self.store.read("nodes.json"), node)
        self.assertEqual(self.store.settings()["selected"], "original-id")
        self.assertNotIn("original-secret", (self.store.home / "nodes.json").read_text())
        self.assertFalse(list(self.store.home.glob("*.bak")))

    def test_protect_or_permission_failure_leaves_old_data_usable(self):
        node = [{"id": "original", "password": "retained-secret"}]
        atomic_json(self.store.home / "nodes.json", node)
        original = (self.store.home / "nodes.json").read_bytes()
        for target in ("enge_spx.storage._private_directory",):
            with patch(target, side_effect=SPXError("access denied")):
                with self.assertRaises(SPXError):
                    self.store.migrate_credentials()
            self.assertEqual((self.store.home / "nodes.json").read_bytes(), original)
        with patch("enge_spx.storage._private_directory"), patch.object(self.backend, "protect", side_effect=SPXError("protect failed")):
            with self.assertRaises(SPXError):
                self.store.migrate_credentials()
        self.assertEqual(self.store.read("nodes.json"), node)
        self.assertFalse((self.store.home / "credentials-state.json").exists())

    def test_partial_migration_can_resume_and_remains_readable(self):
        atomic_json(self.store.home / "nodes.json", [{"id": "keep", "password": "keep-secret"}])
        atomic_json(self.store.home / "settings.json", {"selected": "keep"})
        real = atomic_json
        def fail_settings(path, value):
            if path.name == "settings.json":
                raise PermissionError("locked")
            real(path, value)
        with patch("enge_spx.storage._private_directory"), patch("enge_spx.state.atomic_json", side_effect=fail_settings):
            with self.assertRaises(PermissionError):
                self.store.migrate_credentials()
        self.assertEqual(self.store.read("nodes.json")[0]["id"], "keep")
        self.assertEqual(self.store.settings()["selected"], "keep")
        with patch("enge_spx.storage._private_directory"):
            self.store.migrate_credentials()
        self.assertEqual(self.store.read("credentials-state.json")["state"], "complete")

    def test_completed_migration_does_not_silently_accept_plaintext_downgrade(self):
        self.store.write("settings.json", {"selected": "keep"})
        with patch("enge_spx.storage._private_directory"):
            self.store.migrate_credentials()
        atomic_json(self.store.home / "settings.json", {"selected": "replacement"})
        with self.assertRaises(SPXError):
            self.store.settings()

    def test_explicit_private_legacy_export_keeps_the_encrypted_source_unchanged(self):
        value = [{"id": "kept", "password": "rollback-secret"}]
        self.store.write("nodes.json", value)
        before = (self.store.home / "nodes.json").read_bytes()
        target = self.store.home.parent / "rollback"
        with self.assertRaises(SPXError):
            self.store.export_legacy_credentials(target)
        with patch("enge_spx.storage._private_directory"):
            result = self.store.export_legacy_credentials(target, allow_plaintext=True)
        self.assertTrue(result["plaintext"])
        self.assertEqual(json.loads((target / "nodes.json").read_text()), value)
        self.assertEqual((self.store.home / "nodes.json").read_bytes(), before)
        self.assertEqual(self.store.read("nodes.json"), value)

    def test_export_permission_failure_does_not_leave_a_partial_plaintext_copy(self):
        self.store.write("nodes.json", [{"password": "private-needle"}])
        target = self.store.home.parent / "failed-export"
        with patch("enge_spx.storage._private_directory", side_effect=SPXError("denied")):
            with self.assertRaises(SPXError):
                self.store.export_legacy_credentials(target, allow_plaintext=True)
        self.assertFalse(target.exists())
        self.assertFalse(list(target.parent.glob(".failed-export.spx-export-*")))

    def test_private_posix_files_are_not_claimed_to_be_encrypted(self):
        if os.name == "nt":
            self.skipTest("POSIX policy")
        store = Store(self.store.home / "posix")
        self.assertFalse(store.migrate_credentials()["encrypted"])
        store.write("nodes.json", [{"id": "node"}])
        self.assertEqual((store.home / "nodes.json").stat().st_mode & 0o777, 0o600)


@unittest.skipUnless(os.name == "nt", "Actual Windows current-user DPAPI")
class NativeDPAPITests(unittest.TestCase):
    def test_native_encrypt_round_trip_wrong_entropy_and_corruption(self):
        backend = DPAPI()
        plaintext = "password=private-token 中文".encode("utf-8")
        protected = backend.protect(plaintext, b"purpose-one")
        self.assertNotIn(b"private-token", protected)
        self.assertEqual(backend.unprotect(protected, b"purpose-one"), plaintext)
        for data, context in ((protected, b"wrong-purpose"), (protected[:len(protected)//2], b"purpose-one")):
            with self.assertRaises(SPXError):
                backend.unprotect(data, context)

    def test_real_store_reopens_after_current_user_cross_drive_style_relocation(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Store(Path(folder) / "source")
            source.write("nodes.json", [{"id": "same-node", "password": "native-private"}])
            source.write("settings.json", {"selected": "same-node"})
            source.migrate_credentials()
            import shutil
            target = Path(folder) / "target"
            shutil.copytree(source.home, target)
            reopened = Store(target)
            self.assertEqual(reopened.settings()["selected"], "same-node")
            self.assertEqual(reopened.read("nodes.json")[0]["password"], "native-private")
            self.assertNotIn("native-private", (target / "nodes.json").read_text())


if __name__ == "__main__":
    unittest.main()
