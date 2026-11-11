from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from enge_spx import network_performance as network
from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.engine import Engine
from enge_spx.state import Store, SPXError


def measured():
    return {"schema": 1, "elapsed_ms": 1300, "samples": [
        {"kind": kind, "requested_bytes": size, "bytes_received": size, "result": "measured", "http_status": 200, "tunnel_tls_ms": 30, "first_byte_ms": 50, "total_ms": total, "body_ms": total - 50, "password": "private-guest-password", "body": "private-response"}
        for kind, size, total in (("cold_https", 1024, 100), ("cold_https", 1024, 150), ("download", 1048576, 1000))]}


def guest():
    spec = importlib.util.spec_from_file_location("spx_network_probe_test", PACKAGE_RESOURCES / "checks/network_probe.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class MeasurementEvidenceTests(unittest.TestCase):
    def test_allowlisted_counters_and_rates_have_explicit_units_and_no_guest_content(self):
        raw = measured()
        raw.update(proxy="http://private:password@proxy", path="C:/private-project")
        raw["samples"][2]["request_bytes_per_second"] = float("inf")
        output = network.evidence(raw)
        self.assertEqual(output["status"], "measured")
        self.assertEqual(output["cold_https_first_byte_ms"]["median"], 50)
        self.assertAlmostEqual(output["download"]["request_mbps"], 8.388608)
        self.assertNotIn("private", json.dumps(output))

    def test_incomplete_samples_are_not_zero_speed_or_success(self):
        raw = measured()
        raw["samples"][0].update(result="failed", error_code="tls_certificate_error", first_byte_ms=None)
        raw["samples"][2].update(result="not_run", error_code="time_budget", bytes_received=0)
        output = network.evidence(raw)
        self.assertEqual(output["status"], "partial")
        self.assertEqual(output["cold_https_first_byte_ms"]["count"], 1)
        self.assertIsNone(output["download"]["request_mbps"])
        self.assertIsNone(output["download"]["body_mbps"])

    def test_malformed_schemas_counts_sizes_and_ordered_timings_are_rejected(self):
        mutations = [lambda r: r.update(schema=True), lambda r: r["samples"].pop(), lambda r: r["samples"][0].update(requested_bytes=999), lambda r: r["samples"][0].update(bytes_received=True), lambda r: r["samples"][0].update(first_byte_ms=float("nan")), lambda r: r["samples"][0].update(tunnel_tls_ms=999), lambda r: r["samples"][2].update(bytes_received=1048578)]
        for mutate in mutations:
            raw = measured(); mutate(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                network.evidence(raw)

    def test_guest_requires_a_literal_gateway_and_never_accepts_target_or_credentials(self):
        module = guest()
        self.assertEqual(module.proxy_address("http://172.24.0.2:2080"), ("172.24.0.2", 2080))
        for value in ("http://example.com:2080", "https://172.24.0.2:2080", "http://u:p@172.24.0.2:2080", "http://172.24.0.2:2082", "http://172.24.0.2:2080/?url=secret", "http://172.24.0.2:2080#secret", "\nhttp://172.24.0.2:2080", "http://[::1]:2080"):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                module.proxy_address(value)

    def test_guest_error_codes_never_echo_tls_or_transport_details(self):
        module = guest()
        for error, expected in ((ssl.SSLCertVerificationError("private-password"), "tls_certificate_error"), (TimeoutError("private-password"), "timeout"), (ConnectionRefusedError("private-password"), "connection_refused"), (module.RejectedResponse("private-url"), "response_rejected"), (OSError("private-password"), "proxy_or_transport_failure")):
            self.assertEqual(module.error_code(error), expected)

    def test_guest_explicit_connect_ignores_proxy_env_and_rejects_redirects(self):
        module = guest()
        @contextmanager
        def no_wait(seconds):
            yield
        response = Mock(status=302)
        response.getheader.return_value = None
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(module, "hard_timeout", no_wait), patch.object(module.http.client, "HTTPSConnection", return_value=connection) as create, patch.dict("os.environ", {"NO_PROXY": "*", "HTTPS_PROXY": "http://private-bypass", "ALL_PROXY": "http://private-bypass"}):
            result = module.request("http://172.24.0.2:2080", "cold_https", 1024, 4)
        self.assertEqual(result["result"], "failed")
        self.assertEqual(result["error_code"], "response_rejected")
        self.assertEqual(create.call_args.args[:2], ("172.24.0.2", 2080))
        context = create.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        connection.set_tunnel.assert_called_once_with("speed.cloudflare.com", 443)
        self.assertEqual(connection.request.call_count, 1)
        response.read.assert_not_called()
        response.close.assert_called_once()
        connection.close.assert_called_once()


class MeasurementLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.state = {"phase": "ready", "gateway": "private-gateway-id", "session": "private-session-id", "policy": "policy-a", "confirmed": 1, "proxy": "http://172.24.0.2:2080", "evidence": {"ip": "8.8.8.8"}}
        self.store.write("runtime.json", self.state)
        self.engine = Engine(self.store)
        self.engine.ready = Mock(side_effect=lambda timings=None: self.state)
        self.engine.inspect = Mock(return_value={"Id": self.state["gateway"], "State": {"Running": True}, "NetworkSettings": {"Networks": {self.engine.internal: {"IPAddress": "172.24.0.2"}}}})
        self.engine.docker.run = Mock(return_value=json.dumps(measured()))
        self.engine._shutdown_locked = Mock(return_value={"workspace_stopped": True, "background_stopped": True})

    def test_not_ready_does_not_query_docker_or_start_anything(self):
        self.store.write("runtime.json", {"phase": "stopped"})
        report = self.engine.network_performance()
        self.assertEqual(report["status"], "not_ready")
        self.engine.ready.assert_not_called()
        self.engine.docker.run.assert_not_called()
        self.engine._shutdown_locked.assert_not_called()

    def test_verification_surrounds_stdin_only_final_chain_measurement_and_no_sensitive_report(self):
        report = self.engine.network_performance()
        self.assertEqual(report["status"], "checked")
        self.assertEqual(self.engine.ready.call_count, 2)
        args, kwargs = self.engine.docker.run.call_args
        self.assertEqual(args[:3], ("exec", "-i", self.state["session"]))
        self.assertEqual(json.loads(kwargs["input_data"]), {"proxy": self.state["proxy"]})
        self.assertLessEqual(kwargs["timeout"], 22)
        self.assertNotIn(self.state["proxy"], repr(args))
        self.assertNotIn("private", json.dumps(report))
        self.engine._shutdown_locked.assert_not_called()

    def test_operation_lock_is_available_to_guard_during_transfer(self):
        acquired = threading.Event()
        def perform(*args, **kwargs):
            def guard():
                with self.store.lock(timeout=.5):
                    acquired.set()
            thread = threading.Thread(target=guard); thread.start(); thread.join(1)
            self.assertTrue(acquired.is_set())
            return json.dumps(measured())
        self.engine.docker.run.side_effect = perform
        self.assertEqual(self.engine.network_performance()["status"], "checked")

    def test_changed_workspace_discards_results_and_does_not_stop_or_verify_replacement(self):
        for field, value in (("confirmed", 2), ("policy", "new-policy"), ("session", "replacement"), ("phase", "stopped")):
            self.store.write("runtime.json", self.state)
            self.engine.ready.reset_mock()
            def perform(*args, **kwargs):
                self.store.write("runtime.json", {**self.state, field: value})
                return json.dumps(measured())
            self.engine.docker.run.side_effect = perform
            report = self.engine.network_performance()
            self.assertEqual(report["status"], "stale")
            self.assertEqual(report["measurement"]["status"], "discarded")
            self.assertNotIn("samples", report["measurement"])
            self.assertEqual(self.engine.ready.call_count, 1)
            self.engine._shutdown_locked.assert_not_called()

    def test_wrong_gateway_proxy_is_rejected_before_any_transfer(self):
        self.state["proxy"] = "http://wrong-proxy:2080"
        report = self.engine.network_performance()
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["stop"]["verified"])
        self.engine.docker.run.assert_not_called()

    def test_pre_or_post_verification_failures_stop_and_never_publish_speed_as_verified(self):
        for replies in ([SPXError("private-preflight")], [self.state, SPXError("SPX_PROBE:timeout private-postflight")]):
            self.engine.ready.side_effect = replies
            report = self.engine.network_performance()
            self.assertEqual(report["status"], "failed")
            self.assertTrue(report["stop"]["verified"])
            self.assertNotIn("samples", report.get("measurement", {}))
            self.assertNotIn("private", json.dumps(report))

    def test_target_or_malformed_output_failure_does_not_bypass_or_claim_zero_speed(self):
        for output in ("private-invalid-json", json.dumps({"schema": True}), json.dumps({**measured(), "samples": []})):
            self.engine.docker.run.return_value = output
            report = self.engine.network_performance()
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["verification_after"]["status"], "verified")
            self.assertNotIn("request_mbps", json.dumps(report))
            self.engine._shutdown_locked.assert_not_called()

    def test_target_tls_failure_stops_only_the_unchanged_workspace_and_discards_speed(self):
        raw = measured()
        raw["samples"][2].update(result="failed", error_code="tls_certificate_error", bytes_received=0)
        self.engine.docker.run.return_value = json.dumps(raw)
        report = self.engine.network_performance()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["measurement"], {"status": "discarded", "reason": "tls_certificate_error"})
        self.assertTrue(report["stop"]["verified"])
        self.engine._shutdown_locked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
