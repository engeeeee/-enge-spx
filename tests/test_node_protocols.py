import base64
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.parse

from enge_spx.nodes import normalize, parse_nodes, uri_node
from enge_spx.line_security import managed_line
from enge_spx.state import SPXError

UUID = "12345678-1234-1234-1234-123456789abc"
PUBLIC = base64.urlsafe_b64encode(bytes(range(1, 33))).decode().rstrip("=")
REALITY = f"vless://{UUID}@192.0.2.1:443?security=reality&sni=cdn.example&pbk={PUBLIC}&sid=abcd&fp=chrome&flow=xtls-rprx-vision"


class ProtocolNodeTests(unittest.TestCase):
    def test_084_canonical_nodes_and_persistent_ids_are_unchanged(self):
        fixtures = json.loads((Path(__file__).parent / "fixtures/nodes-0.8.4.json").read_text(encoding="utf-8"))
        for row in fixtures:
            with self.subTest(row=row.get("uri", "VMess JSON")):
                result = uri_node(row["uri"]) if "uri" in row else normalize(row["json"])
                self.assertEqual(result, row["expected"])
                self.assertEqual(normalize(result), result)

    def test_reality_validates_and_preserves_key_sni_short_id_and_vision(self):
        node = uri_node(REALITY)
        tls = node["outbound"]["tls"]
        self.assertEqual(tls["server_name"], "cdn.example")
        self.assertEqual(tls["reality"], {"enabled": True, "public_key": PUBLIC, "short_id": "abcd"})
        self.assertEqual(node["outbound"]["flow"], "xtls-rprx-vision")
        self.assertTrue(tls["utls"]["enabled"])
        self.assertEqual(normalize(node), node)
        self.assertEqual(managed_line(node)["tls"], tls)

    def test_reality_missing_or_unsafe_parameters_fail_without_echoing_values(self):
        raw = uri_node(REALITY)["outbound"]
        variants = []
        for field, value in (("server_name", ""), ("server_name", "192.0.2.1"), ("insecure", True)):
            item = deepcopy(raw); item["tls"][field] = value; variants.append(item)
        for field, value in (("public_key", "private-needle"), ("public_key", "A" * 43), ("short_id", "f"), ("short_id", "ab" * 9)):
            item = deepcopy(raw); item["tls"]["reality"][field] = value; variants.append(item)
        item = deepcopy(raw); item["tls"]["utls"]["enabled"] = False; variants.append(item)
        for value in variants:
            with self.subTest(case=variants.index(value)), self.assertRaises(ValueError) as caught:
                normalize(value)
            self.assertNotIn("private-needle", str(caught.exception))

    def test_vless_and_trojan_ws_grpc_links_keep_transport_parameters(self):
        for protocol, identity in (("vless", UUID), ("trojan", "fixture-secret")):
            for transport, query in (("ws", "path=%2Fchat&host=cdn.example&ed=2048"), ("grpc", "serviceName=spx-service&alpn=h2")):
                value = uri_node(f"{protocol}://{identity}@192.0.2.1:443?security=tls&sni=cdn.example&type={transport}&{query}")["outbound"]
                self.assertEqual(value["transport"]["type"], transport)
                self.assertTrue(value["tls"]["enabled"])
                if transport == "ws":
                    self.assertEqual(value["transport"]["headers"]["Host"], "cdn.example")
                    self.assertEqual(value["transport"]["max_early_data"], 2048)
                else:
                    self.assertEqual(value["transport"]["service_name"], "spx-service")

    def test_ambiguous_unknown_or_conflicting_transport_options_are_rejected(self):
        base = f"vless://{UUID}@192.0.2.1:443?"
        for query in ("type=xhttp", "type=kcp", "type=ws&flow=xtls-rprx-vision", "type=grpc&mode=multi", "type=grpc&host=authority", "type=ws&serviceName=other", "type=ws&path=%2F%0d%0aHeader", "sni=a.example&sni=b.example", "security=reality&pbk=" + PUBLIC, "security=tls&pbk=" + PUBLIC, "security=tls&insecure=true", "type=tcp&path=/ignored", "unknown=private-needle"):
            with self.subTest(query=query), self.assertRaises(ValueError) as caught:
                uri_node(base + query)
            self.assertNotIn("private-needle", str(caught.exception))

    def test_zero_websocket_early_data_normalization_is_idempotent(self):
        node = uri_node(f"vless://{UUID}@192.0.2.1:443?type=ws&ed=0")
        self.assertNotIn("max_early_data", node["outbound"]["transport"])
        self.assertEqual(normalize(node), node)

    def test_hysteria2_alias_credentials_obfuscation_and_bandwidth(self):
        value = uri_node("hy2://user%3Apass%40word@192.0.2.1:443?sni=cdn.example&obfs=salamander&obfs-password=synthetic&upmbps=100&downmbps=200")["outbound"]
        self.assertEqual(value["type"], "hysteria2")
        self.assertEqual(value["password"], "user:pass@word")
        self.assertEqual(value["obfs"]["type"], "salamander")
        self.assertEqual((value["up_mbps"], value["down_mbps"]), (100, 200))
        self.assertNotIn("network", value)  # Both payload networks, carried over QUIC.
        self.assertEqual(managed_line(normalize(value))["type"], "hysteria2")
        for query in ("insecure=1", "obfs=unknown", "obfs-password=missing-type", "mport=1000-2000", "upmbps=-1", "alpn=http/1.1", "downmbps=1.5"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                uri_node("hysteria2://secret@192.0.2.1:443?" + query)

    def test_clash_mihomo_yaml_imports_nodes_and_never_runs_rules_or_providers(self):
        content = f'''proxies:
  - name: Reality
    type: vless
    server: 192.0.2.1
    port: 443
    uuid: {UUID}
    tls: true
    servername: cdn.example
    reality-opts:
      public-key: {PUBLIC}
      short-id: abcd
    client-fingerprint: chrome
    flow: xtls-rprx-vision
  - name: QUIC
    type: hysteria2
    server: 192.0.2.2
    port: 443
    password: fixture
    sni: cdn.example
    up: 100 Mbps
proxy-groups:
  - name: ignored
    type: fallback
    proxies: [DIRECT, Reality]
proxy-providers:
  ignored:
    url: https://private-needle.example/subscription
rules: [MATCH,DIRECT]
'''
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected provider fetch")):
            nodes, warnings = parse_nodes(content)
        self.assertEqual(len(nodes), 2)
        self.assertTrue(warnings)
        self.assertNotIn("private-needle", repr(warnings))
        self.assertEqual(nodes[1]["outbound"]["up_mbps"], 100)

    def test_partial_import_has_bounded_safe_field_errors(self):
        content = json.dumps([{"type": "vless", "server": "192.0.2.1", "server_port": 443, "uuid": "private-needle"}, {"type": "socks", "server": "192.0.2.2", "server_port": 1080}])
        nodes, errors = parse_nodes(content)
        self.assertEqual(len(nodes), 1)
        self.assertIn("uuid", errors[0])
        self.assertNotIn("private-needle", repr(errors))

    def test_json_tls_types_https_and_host_paths_never_downgrade(self):
        for raw in ({"type": "https", "tls": {"enabled": False}}, {"type": "trojan", "tls": {"enabled": "not-a-bool"}}, {"type": "trojan", "tls": {"certificate_path": "C:/private-needle.pem"}}, {"type": "trojan", "tls": {"insecure": True}}, {"type": "trojan", "server_port": 443.5}):
            value = {"server": "192.0.2.1", "server_port": 443, "password": "fixture", **raw}
            with self.subTest(raw=raw), self.assertRaises(ValueError) as caught:
                normalize(value)
            self.assertNotIn("private-needle", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
