import unittest

from enge_spx.backends import DEFAULT_BACKEND, get_backend
from enge_spx.line_security import chain_outbounds
from enge_spx.nodes import uri_node
from enge_spx.proxy import relay_config
from enge_spx.state import SPXError


class BackendContractTests(unittest.TestCase):
    def test_original_single_gateway_config_is_preserved(self):
        node = uri_node("socks5://fixture:private@192.0.2.1:1080")
        outbounds, _ = chain_outbounds(node, relay_config(False))
        result = get_backend().gateway_config(outbounds, "172.19.0.2", False)
        self.assertEqual(result, {"log": {"level": "warn"}, "inbounds": [{"type": "mixed", "tag": "clients", "listen": "172.19.0.2", "listen_port": 2080}], "outbounds": outbounds, "route": {"final": "selected"}})

    def test_local_v2ray_chain_keeps_separate_loopback_diagnostic_entry(self):
        node = uri_node("http://fixture:private@landing.example:8080")
        outbounds, target = chain_outbounds(node, relay_config(True, "http://127.0.0.1:10809"))
        result = DEFAULT_BACKEND.gateway_config(outbounds, "172.19.0.2", True)
        self.assertEqual(target, {"host": "127.0.0.1", "port": 10809})
        self.assertEqual(result["inbounds"][1]["listen"], "127.0.0.1")
        self.assertEqual(result["route"]["rules"][0]["outbound"], "host-line")
        self.assertEqual(result["outbounds"][0]["detour"], "host-line")

    def test_unknown_backend_or_route_never_selects_a_fallback(self):
        with self.assertRaises(SPXError):
            get_backend("not-implemented")
        for values, chained in (([{"type": "direct", "tag": "selected"}], False), ([{"type": "selector", "tag": "selected"}], False), ([{"type": "socks", "tag": "selected", "detour": "missing"}], False), ([{"type": "socks", "tag": "selected"}], True), ([{"type": "socks", "tag": "selected", "detour": "direct"}, {"type": "socks", "tag": "spx-line"}], True)):
            with self.subTest(values=values), self.assertRaises(SPXError):
                DEFAULT_BACKEND.gateway_config(values, "172.19.0.2", chained)

    def test_unverified_hysteria_over_a_tcp_only_local_forward_is_rejected(self):
        values = [{"type": "hysteria2", "tag": "selected", "detour": "host-line"}, {"type": "http", "tag": "host-line"}]
        with self.assertRaises(SPXError):
            DEFAULT_BACKEND.gateway_config(values, "172.19.0.2", True)


if __name__ == "__main__":
    unittest.main()
