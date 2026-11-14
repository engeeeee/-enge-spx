import copy
import importlib.util
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from enge_spx import network_diagnostics as network
from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.engine import Engine
from enge_spx.state import Store, SPXError


def guest(name):
    spec = importlib.util.spec_from_file_location("spx_test_" + name, PACKAGE_RESOURCES / "checks" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def namespace():
    return {"schema": 1, "routes": {"available": True, "ipv4": [{"destination": "172.24.0.0/16", "gateway": "0.0.0.0"}], "ipv6": [{"destination": "::1/128", "gateway": "::"}]}, "dns_servers": ["127.0.0.1"], "network_namespace": "net:[4026539999]", "ipv6_interfaces": True, "language": {"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}, "timezone": {"name": "UTC", "offset_seconds": 0}, "direct_tests": [{"test": test, "target": target, "result": "unreachable", "elapsed_ms": 1} for test, target in (("public_ipv4_tcp", "1.1.1.1"), ("public_ipv6_tcp", "2606:4700:4700::1111"), ("public_dns_udp", "1.1.1.1"))], "system_resolver": {"result": "not_resolved"}}


def browser():
    return {"schema": 1, "available": True, "observation": {"language": "en-US", "languages": ["en-US", "en"], "timezone": "UTC", "offset_minutes": 0, "webrtc": {"available": True, "offer_created": True, "candidates": []}}, "accept_language": "en-US,en;q=0.9", "local_stun_datagrams": 0, "webrtc_policy_file": "disable_non_proxied_udp"}


class EvidenceTests(unittest.TestCase):
    def test_timezone_report_distinguishes_process_tz_from_system_file(self):
        raw = namespace()
        raw["timezone"].update(name="America/Los_Angeles", offset_seconds=-28800, localtime_name="Etc/UTC",
                               localtime_offset_seconds=0, localtime_matches_process_offset=False, localtime_matches_tzif=False,
                               localtime_path="/private-host-data")
        observed = network.environment_evidence(raw)["timezone"]
        self.assertEqual(observed["name"], "America/Los_Angeles")
        self.assertEqual(observed["localtime_name"], "Etc/UTC")
        self.assertIs(observed["localtime_matches_process_offset"], False)
        self.assertIs(observed["localtime_matches_tzif"], False)
        self.assertNotIn("private-host", json.dumps(observed))
        raw["timezone"]["localtime_matches_tzif"] = "true"
        self.assertIsNone(network.environment_evidence(raw)["timezone"]["localtime_matches_tzif"])

    @unittest.skipUnless(hasattr(__import__("time"), "tzset"), "Native Linux libc TZ selection")
    def test_actual_timezone_probe_reads_both_tzif_sources_without_changing_them(self):
        import os
        import time
        from importlib.resources import files
        probe = guest("environment_probe")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = files("tzdata.zoneinfo")
            (root / "Etc").mkdir()
            (root / "America").mkdir()
            utc = (root / "Etc/UTC")
            utc.write_bytes(data.joinpath("Etc/UTC").read_bytes())
            selected = root / "America/Los_Angeles"
            selected.write_bytes(data.joinpath("America/Los_Angeles").read_bytes())
            localtime = root / "localtime"
            localtime.symlink_to(utc)
            before = utc.read_bytes()
            try:
                with patch.dict(os.environ, {"TZ": "America/Los_Angeles"}):
                    evidence = probe.timezone_facts(localtime, root)
                    self.assertEqual(evidence["localtime_offset_seconds"], 0)
                    self.assertEqual(evidence["localtime_name"], "Etc/UTC")
                    self.assertIs(evidence["localtime_matches_process_offset"], False)
                    self.assertIs(evidence["localtime_matches_tzif"], False)
                    localtime.unlink()
                    localtime.symlink_to(selected)
                    evidence = probe.timezone_facts(localtime, root)
                    self.assertIs(evidence["localtime_matches_process_offset"], True)
                    self.assertIs(evidence["localtime_matches_tzif"], True)
            finally:
                time.tzset()
            self.assertEqual(utc.read_bytes(), before)

    def test_environment_filters_unknown_fields_and_never_treats_timeout_as_blocked(self):
        raw = namespace()
        raw.update(password="synthetic-private-password", project="C:/private-project", token="token-secret")
        raw["direct_tests"][0]["result"] = "no_response"
        raw["language"]["LANG"] = "https://username:password@proxy"
        data = network.environment_evidence(raw)
        self.assertEqual(data["direct_tests"][0]["result"], "no_response")
        self.assertEqual(data["language"]["LANG"], "unavailable")
        self.assertNotIn("private", json.dumps(data))
        with self.assertRaises(ValueError):
            network.environment_evidence({**raw, "schema": True})

    def test_browser_filters_credentials_sdp_and_paths_and_observes_actual_languages(self):
        raw = browser()
        raw.update(password="private-password", Cookie="private-cookie", token="private-token")
        raw["observation"]["webrtc"].update(sdp="private-sdp", usernameFragment="private-ice")
        raw["observation"]["webrtc"]["candidates"] = [{"type": "host", "protocol": "udp", "address": "192.168.1.2", "sdp": "private-sdp"}, {"type": "host", "protocol": "udp", "address": "C:/private-project"}]
        data = network.browser_evidence(raw)
        self.assertEqual(data["language"], "en-US")
        self.assertEqual(data["request_languages"], ["en-US", "en"])
        self.assertEqual(data["webrtc"]["candidates"][0]["address"], "192.168.1.2")
        self.assertNotIn("private", json.dumps(data))
        self.assertEqual(network.browser_evidence({"schema": 1, "available": False})["status"], "unavailable")

    def test_address_pseudonyms_are_consistent_within_one_report_and_differ_between_reports(self):
        raw = {"identity": "abcdef012345", "container": "container-private-id", "first": "8.8.8.8", "final": "8.8.8.8", "route": "192.168.1.0/24", "candidate": "eea9a8bb-0000-1111-2222-123456abcdef.local", "ns": "net:[4026539999]", "dns": "127.0.0.1"}
        first, second = network.obscure(raw), network.obscure(raw)
        self.assertEqual(first["first"], first["final"])
        self.assertNotEqual(first["first"], second["first"])
        self.assertEqual(first["dns"], "127.0.0.1")
        for value in raw.values():
            if value != "127.0.0.1":
                self.assertNotIn(value, json.dumps(first))

    def test_safe_error_codes_distinguish_tls_timeout_and_changed_exit_without_echo(self):
        probe = guest("exit_probe")
        self.assertEqual(probe.failure_code(urllib.error.URLError(ssl.SSLCertVerificationError("private-password"))), "tls_certificate_error")
        self.assertEqual(probe.failure_code(TimeoutError("private-password")), "timeout")
        self.assertEqual(probe.failure_code(ValueError("Direct outbound connectivity is available.")), "direct_path_available")
        self.assertEqual(network.failure_code(SPXError("SPX_PROBE:tls_certificate_error private-password")), "tls_certificate_error")
        self.assertEqual(network.failure_code(SPXError("private-password")), "probe_failed")

    def test_timed_measurement_records_failed_hop_without_exception_message(self):
        rows = []
        with self.assertRaises(SPXError):
            network.measured_probe("first_hop", Mock(side_effect=SPXError("private-password")), rows)
        self.assertEqual(rows[0]["scope"], "first_hop")
        self.assertEqual(rows[0]["result"], "failed")
        self.assertGreaterEqual(rows[0]["elapsed_ms"], 0)
        self.assertNotIn("private-password", json.dumps(rows))

    def test_native_host_snapshot_is_read_only_and_bounded_without_public_socket(self):
        with patch("socket.create_connection", side_effect=AssertionError("Host attempted a public socket")):
            result = network.host_facts()
        self.assertIn("routing_available", result)
        self.assertIn("read-only", result["scope"])
        self.assertLess(len(json.dumps(result)), 32768)

    def test_browser_authorization_is_only_on_exec_stdin(self):
        engine = Mock()
        engine.docker.run.return_value = json.dumps(browser())
        token = "a" * 64
        network._exec_json(engine, "browser-id", "browser_probe.py", authorization={"token": token})
        args, kwargs = engine.docker.run.call_args
        self.assertNotIn(token, repr(args))
        self.assertEqual(json.loads(kwargs["input_data"]), {"token": token})
        self.assertIn("-i", args)


class NetworkLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.state = {"phase": "ready", "session": "session-id", "browser_token": "b" * 64, "evidence": {"ip": "8.8.8.8", "line_ip": "9.9.9.9", "timezone": "UTC", "country": "Synthetic Country", "city": "Test City"}}
        self.store.write("runtime.json", self.state)
        self.engine = Engine(self.store)
        self.engine.inspect = Mock(return_value=None)
        def verified(timings=None):
            if timings is not None:
                network.measured_probe("first_hop", lambda: {"ip": "9.9.9.9"}, timings)
                network.measured_probe("final_exit", lambda: {"ip": "8.8.8.8"}, timings)
            return self.state
        self.engine.ready = Mock(side_effect=verified)
        self.engine._shutdown_locked = Mock(return_value={"workspace_stopped": True, "background_stopped": True})
        self.host = patch("enge_spx.network_diagnostics.host_facts", return_value={"scope": "control_host read-only", "routing_available": True})
        self.host.start()
        self.addCleanup(self.host.stop)

    def test_not_ready_does_not_start_docker_or_attempt_connection(self):
        self.store.write("runtime.json", {"phase": "stopped"})
        with patch.object(self.engine.docker, "run", side_effect=AssertionError("Unexpected Docker call")):
            report = self.engine.network_diagnostics()
        self.assertEqual(report["status"], "not_ready")
        self.engine.ready.assert_not_called()
        self.engine._shutdown_locked.assert_not_called()

    def test_scoped_success_retains_guard_and_does_not_auto_start_browser(self):
        with patch("enge_spx.network_diagnostics._exec_json", return_value=namespace()):
            report = self.engine.network_diagnostics(browser=False)
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["objects"]["browser"]["status"], "skipped")
        self.assertEqual(report["objects"]["first_hop"]["scope"], "first_hop")
        self.engine._shutdown_locked.assert_not_called()
        self.assertEqual(self.store.read("runtime.json")["phase"], "ready")
        for value in (self.state["browser_token"], self.state["evidence"]["ip"], self.state["evidence"]["line_ip"], self.state["session"]):
            self.assertNotIn(value, json.dumps(report))

    def test_actual_tcp_or_udp_bypass_immediately_requests_verified_shutdown(self):
        for index, result in ((0, "connected"), (1, "connected"), (2, "replied")):
            raw = namespace()
            raw["direct_tests"][index]["result"] = result
            with patch("enge_spx.network_diagnostics._exec_json", return_value=raw):
                report = self.engine.network_diagnostics()
            self.assertEqual(report["status"], "unsafe")
            self.assertTrue(report["stop"]["verified"])
            self.assertEqual(report["objects"]["browser"]["status"], "not_run")
        self.assertEqual(self.engine._shutdown_locked.call_count, 3)

    def test_failed_connection_reports_stage_and_does_not_claim_a_failed_stop(self):
        self.engine.ready.side_effect = SPXError("SPX_PROBE:timeout private-password")
        self.engine._shutdown_locked.side_effect = SPXError("Docker is unavailable")
        report = self.engine.network_diagnostics()
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["stop"]["verified"])
        self.assertEqual(report["objects"]["connection"]["reason"], "timeout")
        self.assertNotIn("private-password", json.dumps(report))

    def test_browser_not_running_or_failed_observation_is_partial_not_a_pass(self):
        with patch("enge_spx.network_diagnostics._exec_json", return_value=namespace()):
            report = self.engine.network_diagnostics()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["objects"]["browser"]["status"], "not_running")
        self.engine._shutdown_locked.assert_not_called()

    def test_actual_browser_language_timezone_and_local_webrtc_are_read_only(self):
        self.engine.inspect.return_value = {"Id": "browser-id", "State": {"Running": True}}
        def execute(engine, container, name, **kwargs):
            return browser() if name == "browser_probe.py" else namespace()
        with patch("enge_spx.network_diagnostics._exec_json", side_effect=execute), patch("enge_spx.browser_security.validate_container"), patch("enge_spx.workspace_profiles.validate_mounts"):
            report = self.engine.network_diagnostics()
        evidence = report["objects"]["browser"]
        self.assertEqual(evidence["status"], "observed")
        self.assertTrue(evidence["timezone_matches_session_offset"])
        self.assertTrue(evidence["language_matches_session_primary"])
        self.assertEqual(evidence["webrtc"]["local_udp_observation"], "none_observed")
        self.assertIn("public STUN/TURN not tested", evidence["webrtc"]["scope"])
        self.assertEqual(self.store.settings()["timezone"], "America/Los_Angeles")
        self.engine._shutdown_locked.assert_not_called()

    def test_browser_sandbox_or_identity_failure_stops_without_observation(self):
        self.engine.inspect.return_value = {"Id": "browser-id", "State": {"Running": True}}
        with patch("enge_spx.network_diagnostics._exec_json", return_value=namespace()) as execute, patch("enge_spx.browser_security.validate_container", side_effect=SPXError("bad sandbox")):
            report = self.engine.network_diagnostics()
        self.assertEqual(report["status"], "unsafe")
        self.assertEqual(execute.call_count, 1)
        self.engine._shutdown_locked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
