import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from enge_spx.engine import Engine, OWNER
from enge_spx.nodes import parse_nodes, normalize, uri_node, fetch_subscription
from enge_spx.state import Store, SPXError


UUID = "7fd17738-c109-4baa-8342-a429c4bf795e"


class NodeTests(unittest.TestCase):
    def test_trojan_password_and_sni(self):
        nodes, errors = parse_nodes("trojan://p%40ss%3Aword@203.0.113.2:443?sni=example.com#Tokyo")
        self.assertFalse(errors)
        self.assertEqual(nodes[0]["label"], "Tokyo")
        self.assertEqual(nodes[0]["outbound"]["password"], "p@ss:word")
        self.assertEqual(nodes[0]["outbound"]["tls"]["server_name"], "example.com")

    def test_vless_uuid_validation(self):
        node = uri_node(f"vless://{UUID}@example.com:443?security=tls&type=tcp")
        self.assertEqual(node["outbound"]["uuid"], UUID)
        with self.assertRaises(ValueError):
            uri_node("vless://bad-uuid@example.com")

    def test_unsupported_transport_is_rejected(self):
        for query in ("type=ws", "type=grpc", "security=reality", "flow=xtls-rprx-vision", "fp=chrome", "allowInsecure=1"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                uri_node("trojan://secret@example.com:443?" + query)

    def test_shadowsocks_sip002_and_legacy(self):
        credentials = base64.urlsafe_b64encode(b"aes-128-gcm:pass@word").decode().rstrip("=")
        node = uri_node(f"ss://{credentials}@example.com:8388#test")
        self.assertEqual(node["outbound"]["password"], "pass@word")
        legacy = base64.b64encode(b"aes-256-gcm:password@example.com:443").decode()
        self.assertEqual(uri_node("ss://" + legacy)["outbound"]["method"], "aes-256-gcm")

    def test_shadowsocks_plugin_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            uri_node("ss://YWVzLTEyOC1nY206cGFzcw@example.com:8388?plugin=v2ray-plugin")

    def test_vmess_aead(self):
        value = {"add": "example.com", "port": 443, "id": UUID, "aid": 0, "net": "tcp", "tls": "tls", "ps": "vmess"}
        uri = "vmess://" + base64.b64encode(json.dumps(value).encode()).decode()
        self.assertTrue(uri_node(uri)["outbound"]["tls"]["enabled"])
        value["aid"] = 64
        with self.assertRaises(ValueError):
            uri_node("vmess://" + base64.b64encode(json.dumps(value).encode()).decode())

    def test_subscription_deduplicates_and_reports_partial_import(self):
        line = "trojan://password@example.com:443"
        nodes, errors = parse_nodes(base64.b64encode((line + "\n" + line + "\ntrojan://password@example.com?type=ws").encode()).decode())
        self.assertEqual(len(nodes), 1)
        self.assertEqual(len(errors), 1)
        self.assertNotIn("password", errors[0])

    def test_clash_tls_not_downgraded(self):
        config = "proxies:\n  - name: valid\n    type: trojan\n    server: example.com\n    port: 443\n    password: secret\n"
        nodes, _ = parse_nodes(config)
        self.assertTrue(nodes[0]["outbound"]["tls"]["enabled"])
        with self.assertRaises(SPXError):
            parse_nodes(config + "    skip-cert-verify: true\n")

    def test_json_preserves_no_external_data_fetch(self):
        nodes, _ = parse_nodes(json.dumps({"type": "trojan", "host": "203.0.113.2", "port": 443, "password": "secret", "data": "https://example.com/private", "udp": True}))
        self.assertNotIn("data", nodes[0]["outbound"])
        self.assertEqual(nodes[0]["outbound"]["network"], "tcp")

    def test_import_limits_and_yaml_code(self):
        with self.assertRaises(SPXError):
            parse_nodes("x" * (2 * 1024 * 1024 + 1))
        with self.assertRaises(SPXError):
            parse_nodes("proxies: !!python/object/apply:os.system ['echo bad']")

    def test_subscription_requires_https(self):
        for url in ("http://example.com/token", "file:///etc/passwd", "https://user:secret@example.com"):
            with self.subTest(url=url), self.assertRaises(SPXError):
                fetch_subscription(url)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.store = Store(self.base / "private")

    def test_atomic_unicode_persistence(self):
        self.store.write("test.json", {"name": "项目 文件夹", "value": 1})
        self.assertEqual(self.store.read("test.json")["name"], "项目 文件夹")
        self.store.write("test.json", {"value": 2})
        self.assertEqual(self.store.read("test.json"), {"value": 2})
        self.assertFalse(list(self.store.home.glob(".next-*")))

    def test_instance_survives_restart(self):
        self.assertEqual(Store(self.store.home).instance, self.store.instance)

    def test_operation_lock_excludes_second_process_handle(self):
        with self.store.lock():
            with self.assertRaises(SPXError):
                with self.store.lock():
                    pass

    def test_project_paths(self):
        project = self.base / "项目 with spaces"
        project.mkdir()
        directory, identity = self.store.project(str(project))
        self.assertEqual(directory, project.resolve())
        self.assertEqual(len(identity), 16)
        for path in (self.base, self.store.home, self.store.home.parent):
            with self.assertRaises(SPXError):
                self.store.project(str(path))

    def test_corrupt_configuration_is_not_reset(self):
        (self.store.home / "settings.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(SPXError):
            self.store.settings()


class GateTests(unittest.TestCase):
    setUp = StateTests.setUp
    def engine(self):
        engine = Engine(self.store)
        def stop(reason):
            self.store.write("runtime.json", {"phase": "stopped", "reason": reason})
        engine._stop = Mock(side_effect=stop)
        return engine

    def test_unconfirmed_environment_rejects_work(self):
        engine = self.engine()
        with self.assertRaises(SPXError):
            engine.ready()

    def test_expired_evidence_cannot_be_confirmed(self):
        self.store.write("runtime.json", {"phase": "review", "checked": time.time() - 301})
        engine = self.engine()
        with self.assertRaises(SPXError):
            engine.confirm()
        engine._stop.assert_called_once()
        self.assertEqual(self.store.read("runtime.json")["phase"], "stopped")

    def test_ip_change_during_confirmation_stops_environment(self):
        self.store.write("runtime.json", {"phase": "review", "checked": time.time(), "evidence": {"ip": "1.1.1.1"}})
        engine = self.engine()
        engine.audit_topology = Mock()
        engine.probe = Mock(return_value={"ip": "8.8.8.8"})
        engine.start_guard = Mock()
        with self.assertRaises(SPXError):
            engine.confirm()
        engine._stop.assert_called_once()
        engine.start_guard.assert_not_called()

    def test_guard_disconnect_stops_existing_environment(self):
        self.store.write("runtime.json", {"phase": "ready", "heartbeat": time.time() - 101})
        engine = self.engine()
        engine.audit_topology = Mock()
        with self.assertRaises(SPXError):
            engine.ready()
        engine._stop.assert_called_once()

    def test_ip_change_after_confirmation_stops_environment(self):
        self.store.write("runtime.json", {"phase": "ready", "heartbeat": time.time(), "evidence": {"ip": "1.1.1.1"}})
        engine = self.engine()
        engine.audit_topology = Mock()
        engine.probe = Mock(return_value={"ip": "8.8.8.8"})
        with self.assertRaises(SPXError):
            engine.ready()
        engine._stop.assert_called_once()

    def test_unrelated_docker_objects_are_never_owned(self):
        with self.assertRaises(SPXError):
            self.engine().owned({"Config": {"Labels": {OWNER: "someone-else"}}})

    def test_failed_probe_clears_confirmation(self):
        engine = self.engine()
        engine.doctor = Mock()
        engine.setup = Mock(return_value={"session": "id"})
        engine.probe = Mock(side_effect=SPXError("probe failed"))
        with self.assertRaises(SPXError):
            engine.check()
        self.assertEqual(self.store.read("runtime.json")["phase"], "stopped")


def load_container(name):
    from enge_spx.brand import CONTAINERS
    path = CONTAINERS / (name + ".py")
    spec = importlib.util.spec_from_file_location("test_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrowserAndLeaseTests(unittest.TestCase):
    def test_authorization_urls(self):
        browser = load_container("browser")
        for url in ("https://auth.example.com/login?a=1", "http://localhost:1455/auth/callback?code=test", "http://127.0.0.1:8080/"):
            self.assertTrue(browser.allowed_url(url))
        for url in ("file:///etc/passwd", "javascript:alert(1)", "http://evil.example", "https://u:p@example.com", "http://127.0.0.1.evil.example", "https://example.com\n--bad", "--no-sandbox"):
            self.assertFalse(browser.allowed_url(url))

    def test_gateway_lease_expires_without_host(self):
        gateway = load_container("gateway")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lease.json"
            with patch.object(gateway, "Path", return_value=path):
                for offset, valid in ((100, True), (-1, False), (400, False)):
                    path.write_text(json.dumps({"expires": time.time() + offset}))
                    self.assertEqual(gateway.lease_valid(), valid)
                path.write_text("broken")
                self.assertFalse(gateway.lease_valid())


class CLITests(unittest.TestCase):
    def test_tool_flags_reach_the_tool_in_original_order(self):
        from enge_spx.__main__ import main
        for tail in (["claude", "--continue"], ["claude", "-p", "hello", "--model", "sonnet"], ["codex", "--help"], ["codex", "exec", "hello"]):
            engine = Mock()
            engine.tool_command.return_value = ["not-executed"]
            with self.subTest(tail=tail), patch("sys.argv", ["spx", *tail]), patch("enge_spx.__main__.Store"), patch("enge_spx.__main__.Engine", return_value=engine), patch("enge_spx.__main__.subprocess.call", return_value=0):
                self.assertEqual(main(), 0)
                self.assertEqual(engine.tool_command.call_args.args[1], list(tail))


if __name__ == "__main__":
    unittest.main()
