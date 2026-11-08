import ipaddress
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import httpx

from enge_spx.engine import Engine
from enge_spx.line_security import chain_outbounds, managed_line, line_rules, v2ray_rules, LineSecurityError, LINE_CHECK_CODE
from enge_spx.nodes import fetch_subscription, normalize, uri_node
from enge_spx.proxy import relay_config, validate_relay, route_config, download_proxy, proxy_url
from enge_spx.state import Store, SPXError


class LineSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / "private")
        self.landing = uri_node("socks5://user:private@landing.example:1080")
        self.line = normalize({"type": "trojan", "server": "line.example", "server_port": 443, "password": "line-private"})
        self.store.write("nodes.json", [self.landing, self.line])
        self.relay = relay_config(True, "", True, "managed", self.line["id"], "203.0.113.10")
        self.store.write("settings.json", {**self.store.settings(), "selected": self.landing["id"], "relay": self.relay})

    def test_fixed_line_has_no_direct_or_automatic_fallback_and_keeps_tls_name(self):
        outbounds, target = chain_outbounds(self.landing, self.relay, self.line)
        self.assertIsNone(target)
        self.assertEqual(outbounds[0]["server"], "landing.example")
        self.assertEqual(outbounds[0]["detour"], "spx-line")
        self.assertEqual(outbounds[1]["server"], "203.0.113.10")
        self.assertEqual(outbounds[1]["tls"]["server_name"], "line.example")
        self.assertEqual({outbound["type"] for outbound in outbounds}, {"trojan", "socks"})
        self.assertNotIn("detour", outbounds[1])
        self.assertEqual(validate_relay(self.relay), self.relay)

    def test_bootstrap_requires_an_ip_without_resolving_host_dns(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("host DNS leak")):
            with self.assertRaises(SPXError):
                managed_line(self.line)
            self.assertEqual(managed_line(self.line, "203.0.113.10")["server"], "203.0.113.10")
        for address in ("127.0.0.1", "0.0.0.0", "169.254.1.1", "224.0.0.1", "::1", "invalid"):
            with self.subTest(address=address), self.assertRaises(SPXError):
                managed_line(self.line, address)

    def test_plain_first_hop_and_same_node_are_rejected(self):
        for uri in ("socks5://203.0.113.2:1080", "http://203.0.113.2:8080"):
            with self.subTest(uri=uri), self.assertRaises(SPXError):
                managed_line(uri_node(uri))
        with self.assertRaises(SPXError):
            chain_outbounds(self.line, self.relay, self.line)

    def test_local_compatibility_preserves_landing_domain_for_v2ray_routing(self):
        relay = relay_config(True, "http://user:private@127.0.0.1:10809")
        outbounds, target = chain_outbounds(self.landing, relay)
        self.assertEqual(outbounds[0]["server"], "landing.example")
        self.assertEqual(outbounds[0]["detour"], "host-line")
        self.assertEqual(target, {"host": "127.0.0.1", "port": 10809})
        self.assertEqual(line_rules(outbounds)[0]["outbound"], "host-line")

    def test_gateway_setup_never_uses_host_dns_in_either_line_mode(self):
        for relay in (self.relay, relay_config(True, "http://127.0.0.1:10809")):
            with self.subTest(mode=relay["mode"]):
                self.store.write("settings.json", {**self.store.settings(), "relay": relay})
                engine = Engine(self.store)
                engine.image_ids = Mock(return_value={"gateway": "gateway-image", "work": "work-image"})
                engine.networks = Mock(return_value=("172.18.0.2", "172.18.0.3"))
                engine.ensure_container = Mock(side_effect=[{"Id": "gateway", "NetworkSettings": {"Networks": {engine.external: {}}}}, {"Id": "session"}])
                with patch("enge_spx.engine.socket.getaddrinfo", side_effect=AssertionError("host DNS leak")):
                    state = engine.setup()
                config = self.store.read("gateway/config.json")
                check = next(inbound for inbound in config["inbounds"] if inbound["listen_port"] == 2082)
                self.assertEqual(check["listen"], "127.0.0.1")
                self.assertEqual(state["line_proxy"], "http://127.0.0.1:2082")
                self.assertEqual(config["outbounds"][0]["server"], "landing.example")

    def test_line_change_is_rejected_before_querying_unchanged_landing(self):
        engine = Engine(self.store)
        engine.probe_line = Mock(return_value={"ip": "8.8.8.8"})
        engine.probe = Mock(return_value={"ip": "9.9.9.9", "direct_blocked": True})
        state = {"line_proxy": "http://127.0.0.1:2082", "line_mode": "local", "evidence": {"ip": "9.9.9.9", "line_ip": "1.1.1.1"}}
        with self.assertRaises(LineSecurityError):
            engine.probe_chain(state)
        engine.probe.assert_not_called()
        state["evidence"]["line_ip"] = "8.8.8.8"
        evidence = engine.probe_chain(state)
        self.assertEqual(evidence["line_ip"], "8.8.8.8")
        self.assertEqual(evidence["ip"], "9.9.9.9")

    def test_expected_line_exit_blocks_first_check_and_guard_preserves_reason(self):
        relay = {**self.relay, "expected_ip": "1.1.1.1"}
        self.store.write("settings.json", {**self.store.settings(), "relay": relay})
        engine = Engine(self.store)
        engine.probe_line = Mock(return_value={"ip": "8.8.8.8"})
        engine.probe = Mock()
        engine.audit_topology = Mock()
        engine._stop = Mock(side_effect=lambda reason: self.store.write("runtime.json", {"phase": "stopped", "reason": reason}))
        self.store.write("runtime.json", {"phase": "ready", "heartbeat": time.time(), "line_proxy": "http://127.0.0.1:2082"})
        with self.assertRaises(LineSecurityError):
            engine.ready()
        self.assertIn("前置线路", self.store.read("runtime.json")["reason"])
        self.assertEqual(self.store.read("runtime.json")["phase"], "stopped")
        engine.probe.assert_not_called()

    def test_invalid_line_probe_is_redacted_and_never_falls_back(self):
        engine = Engine(self.store)
        engine.docker = Mock()
        for payload in ('{"ip":"127.0.0.1"}', '{}', 'invalid'):
            engine.docker.run.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(LineSecurityError):
                engine.probe_line({"gateway": "gateway"})
        engine.docker.run.side_effect = SPXError("http://user:private@proxy")
        with self.assertRaises(LineSecurityError) as caught:
            engine.probe_line({"gateway": "gateway"})
        self.assertNotIn("private", str(caught.exception))

    def test_line_diagnostic_ignores_injected_proxy_bypass_environment(self):
        from contextlib import redirect_stdout
        fake = Mock()
        fake.open.side_effect = [io.BytesIO(b'{"ip":"8.8.8.8"}'), io.BytesIO(b'8.8.8.8\n')]
        def opener(handler):
            self.assertEqual(handler.proxies, {"http": "http://127.0.0.1:2082", "https": "http://127.0.0.1:2082"})
            self.assertFalse(any(key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy") for key in os.environ))
            return fake
        out = io.StringIO()
        poison = {"NO_PROXY": "*", "no_proxy": "api.ipify.org", "HTTPS_PROXY": "http://127.0.0.1:9", "all_proxy": "http://untrusted.example"}
        with patch.dict(os.environ, poison), patch("urllib.request.build_opener", side_effect=opener), redirect_stdout(out):
            exec(LINE_CHECK_CODE, {})
        self.assertEqual(json.loads(out.getvalue())["ip"], "8.8.8.8")

    def test_v2ray_rules_use_destination_and_do_not_export_credentials(self):
        rules = v2ray_rules(self.landing)
        self.assertEqual(rules[0]["domain"], ["full:landing.example"])
        self.assertEqual(rules[0]["outboundTag"], "proxy")
        self.assertNotIn("private", json.dumps(rules))
        numeric = v2ray_rules(uri_node("socks5://203.0.113.4:1080"))
        self.assertEqual(numeric[0]["ip"], ["203.0.113.4/32"])

    def test_importing_line_keeps_existing_landing_selection(self):
        self.store.write("nodes.json", [self.landing])
        engine = Engine(self.store)
        engine._stop = Mock()
        engine.save_nodes([self.line], append=True)
        self.assertEqual(self.store.settings()["selected"], self.landing["id"])
        self.assertEqual({node["id"] for node in self.store.read("nodes.json")}, {self.landing["id"], self.line["id"]})

    def test_managed_downloads_use_separate_local_proxy_or_fail_closed(self):
        config = relay_config(True, "http://u:private@127.0.0.1:10809", True, "managed", self.line["id"], "203.0.113.10")
        self.assertEqual(proxy_url(config), "http://u:private@127.0.0.1:10809")
        self.assertIn("10809", download_proxy(config)[0])
        self.assertNotIn("download_outbound", route_config(config))
        with patch("enge_spx.proxy.detect_system_proxy", side_effect=SPXError("missing")):
            with self.assertRaises(SPXError):
                download_proxy(self.relay)
        self.assertEqual(download_proxy({**self.relay, "downloads": False}), (None, "直接连接"))

    def test_download_proxy_can_be_set_before_importing_a_line_or_landing(self):
        config = relay_config(False, "socks5://127.0.0.1:10808", True)
        self.assertEqual(route_config(config), {"enabled": False})
        self.assertEqual(validate_relay(config), config)
        with patch("enge_spx.proxy.detect_system_proxy", side_effect=AssertionError("Unexpected lookup")):
            self.assertEqual(download_proxy(config)[0], "socks5://127.0.0.1:10808")
        engine = Engine(self.store)
        engine._stop = Mock()
        engine.save_settings(self.landing["id"], self.store.settings()["timezone"], self.store.settings()["context"], config)
        self.assertEqual(proxy_url(self.store.settings()["relay"]), "socks5://127.0.0.1:10808")

    def test_subscription_uses_explicit_proxy_and_rejects_http_redirect(self):
        seen = []
        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/leak?private=1"})
        from enge_spx.downloads import client
        with patch("enge_spx.downloads.client", side_effect=lambda proxy: client(proxy=None, transport=httpx.MockTransport(handler))) as factory:
            with self.assertRaises(SPXError):
                fetch_subscription("https://subscription.example/token", "socks5://127.0.0.1:10808")
        factory.assert_called_once_with("socks5://127.0.0.1:10808")
        self.assertEqual(seen, ["https://subscription.example/token"])


if __name__ == "__main__":
    unittest.main()
