import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from enge_spx import browser_security
from enge_spx.brand import CONTAINERS
from enge_spx.engine import Docker, Engine
from enge_spx.redaction import redact, values
from enge_spx.state import SPXError, Store


def resource(name):
    spec = importlib.util.spec_from_file_location("spx_security_" + name, CONTAINERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SandboxTests(unittest.TestCase):
    def test_chromium_reports_both_supported_table_formats_and_rejects_partial_sandbox(self):
        status = resource("sandbox_status")
        for label, value in (("Namespace sandbox", "Yes"), ("Layer 1 Sandbox", "Namespace")):
            html = "<table>" + "".join("<tr><td>" + key + "</td><td>" + val + "</td></tr>" for key, val in ((label, value), ("PID namespaces", "Yes"), ("Network namespaces", "Yes"), ("Seccomp-BPF sandbox", "Yes"))) + "</table>"
            self.assertTrue(all(status.parse_status(html).values()))
            with self.assertRaises(RuntimeError):
                status.parse_status(html.replace("<td>Yes</td>", "<td>No</td>", 1))

    def test_container_policy_rejects_each_privilege_expansion(self):
        policy = json.loads(browser_security.PROFILE.read_text())
        good = {"Config": {"User": "1000:1000"}, "HostConfig": {"Privileged": False, "CapDrop": ["ALL"], "CapAdd": [], "ReadonlyRootfs": True, "SecurityOpt": ["no-new-privileges", "seccomp=" + json.dumps(policy)]}}
        browser_security.validate_container(good)
        for field, value in (("Privileged", True), ("CapAdd", ["SYS_ADMIN"]), ("CapDrop", []), ("ReadonlyRootfs", False), ("SecurityOpt", ["no-new-privileges", "seccomp=unconfined"])):
            invalid = copy.deepcopy(good)
            invalid["HostConfig"][field] = value
            with self.assertRaises(SPXError):
                browser_security.validate_container(invalid)
        invalid = copy.deepcopy(good)
        invalid["Config"]["User"] = "0"
        with self.assertRaises(SPXError):
            browser_security.validate_container(invalid)

    def test_status_requires_kernel_evidence_from_the_actual_renderer(self):
        good = {"schema": 1, **dict.fromkeys(("namespace", "pid_namespace", "network_namespace", "seccomp_bpf"), True), "renderer": dict.fromkeys(("non_root", "no_new_privileges", "no_capabilities", "seccomp", "additional_seccomp_filter", "nested_pid_namespace"), True)}
        browser_security.validate_status(good)
        for key in good["renderer"]:
            invalid = copy.deepcopy(good)
            invalid["renderer"][key] = False
            with self.assertRaises(SPXError):
                browser_security.validate_status(invalid)
        with self.assertRaises(SPXError):
            browser_security.validate_status({})

    def test_policy_has_no_unconfined_default_and_only_the_audited_unconditional_additions(self):
        policy = json.loads(browser_security.PROFILE.read_text())
        self.assertEqual(policy["defaultAction"], "SCMP_ACT_ERRNO")
        for item in policy["syscalls"]:
            if item.get("action") == "SCMP_ACT_ALLOW" and not item.get("includes", {}).get("caps"):
                self.assertFalse({"mount", "setns", "bpf", "pivot_root"} & set(item["names"]))
                if "unshare" in item["names"]:
                    self.assertEqual(item["args"], [{"index": 0, "value": 268435456, "op": "SCMP_CMP_EQ"}])


class CredentialBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.store = Store(self.base / "private")

    def test_stdin_credentials_are_absent_from_argv_and_container_environment(self):
        engine = Engine(self.store)
        engine.docker = Mock()
        value = {"outbounds": [{"password": "private-needle"}]}
        engine.deliver_secret("gateway-id", "gateway", value)
        call = engine.docker.run.call_args
        self.assertEqual(json.loads(call.kwargs["input_data"]), value)
        self.assertNotIn("private-needle", repr(call.args))
        engine.docker.secret_env = {}
        token = "c" * 64
        self.assertEqual(engine.control_env({"browser_token": token}), ["--env", "SPX_BROWSER_TOKEN"])
        self.assertEqual(engine.docker.secret_env["SPX_BROWSER_TOKEN"], token)
        self.assertFalse(any("TOKEN" in item for item in engine.proxy_env({"proxy": "http://172.18.0.2:2080"})))

    def test_docker_stdin_failure_does_not_echo_the_input_or_raw_error(self):
        docker = Docker("default")
        docker.executable = "docker"
        with patch("enge_spx.engine.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "private-needle")):
            with self.assertRaises(SPXError) as caught:
                docker.run("exec", "-i", "container", input_data="private-needle")
        self.assertNotIn("private-needle", str(caught.exception))

    def test_error_scrubber_handles_urls_json_and_encoded_known_secrets(self):
        secret = "p@ss word"
        known = values({"outbound": {"password": secret}, "browser_token": "a" * 64})
        text = redact('http://user:p%40ss%20word@proxy:88 password="p@ss word" raw=p%40ss+word token=' + "a" * 64, known)
        for value in (secret, "p%40ss%20word", "p%40ss+word", "a" * 64):
            self.assertNotIn(value, text)
        self.assertIn("REDACTED", text)

    def test_delete_proxy_removes_persistent_runtime_references_without_removing_accounts(self):
        self.store.write("nodes.json", [{"id": "delete", "password": "private-needle"}, {"id": "keep"}])
        self.store.write("settings.json", {**self.store.settings(), "selected": "delete", "relay": {"enabled": False}})
        self.store.write("runtime.json", {"phase": "ready", "browser_token": "private-token"})
        for name in ("gateway/config.json", "relay.json", "browser-token.json"):
            self.store.write(name, {"password": "private-needle"})
        engine = Engine(self.store)
        engine.docker.executable = None
        engine.delete_node("delete")
        self.assertEqual(self.store.settings()["selected"], "keep")
        self.assertEqual(self.store.read("nodes.json"), [{"id": "keep"}])
        self.assertEqual(self.store.read("runtime.json")["phase"], "stopped")
        self.assertFalse(any((self.store.home / name).exists() for name in ("gateway/config.json", "relay.json", "browser-token.json")))
        engine.clear_proxy_credentials()
        self.assertEqual(self.store.read("nodes.json"), [])
        self.assertFalse(self.store.settings()["relay"]["enabled"])

    def test_attach_rejects_stale_session_before_any_docker_action(self):
        engine = Engine(self.store)
        engine.docker = Mock()
        project = self.base / "project"
        project.mkdir()
        for state in ({"phase": "stopped"}, {"phase": "ready", "session": "different", "heartbeat": time.time()}, {"phase": "ready", "session": "same", "heartbeat": time.time() - 101}):
            self.store.write("runtime.json", state)
            with self.assertRaises(SPXError):
                engine.attach_command(str(project), "claude", "same", "owned")
        engine.docker.run.assert_not_called()

    def test_internal_children_never_take_the_parent_migration_lock(self):
        from enge_spx.__main__ import main
        for action in ("guard", "relay", "forward"):
            engine = Mock()
            engine.guard.return_value = None
            with patch("enge_spx.__main__.Store", return_value=self.store), patch("enge_spx.__main__.Engine", return_value=engine), patch.object(self.store, "migrate_credentials") as migrate, patch("enge_spx.relay.main"), patch("enge_spx.forward.main"), patch("sys.argv", ["spx", action]), patch("sys.stdout", io.StringIO()):
                self.assertEqual(main(), 0)
            migrate.assert_not_called()

    def test_emergency_stop_can_revoke_when_runtime_credentials_cannot_be_decrypted(self):
        self.store.write("settings.json", {**self.store.settings(), "context": "default"})
        metadata = self.store.read("controller-context.json")
        self.assertEqual(metadata["instance"], self.store.instance)
        self.assertEqual(metadata["context"], "default")
        engine = Engine(self.store, stop_context=metadata["context"])
        engine.docker.executable = None
        real_read = self.store.read
        def read(name, default=None):
            if name in ("runtime.json", "settings.json", "nodes.json", "relay.json"):
                raise SPXError("cannot decrypt")
            return real_read(name, default)
        with patch.object(self.store, "read", side_effect=read):
            engine.stop()
        self.assertEqual(real_read("runtime.json")["phase"], "stopped")

    @unittest.skipIf(os.name == "nt", "Container helper uses Linux ownership and O_NOFOLLOW")
    def test_container_ram_file_is_private_and_rejects_symlinks(self):
        helper = resource("runtime_secret")
        target = self.base / "ram" / "config.json"
        helper.write_private(target, {"password": "private-needle"})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        target.unlink()
        other = self.base / "other.json"
        other.write_text("unchanged")
        target.symlink_to(other)
        with self.assertRaises(OSError):
            helper.write_private(target, {})
        self.assertEqual(other.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
