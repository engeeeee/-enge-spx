import copy
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from enge_spx import resource_recording as recording
from enge_spx.state import SPXError


def evidence(memory=1000):
    return {"schema": 1, "sampled": 1234, "host": {"available": True, "cpu_percent": 5, "memory_used": memory * 100, "memory_total": 1000000},
            "app": [{"pid": 12345, "created": 67890, "name": "ENGE SPX 控制进程", "available": True, "cpu_percent": None, "memory_bytes": memory, "private_bytes": memory // 2}],
            "desktop": [{"pid": 54321, "created": 98765, "name": "private-host-name", "scope": "wsl", "available": True, "cpu_percent": 20, "memory_bytes": 5000}], "background_unavailable": 0,
            "containers": {"available": True, "truncated": False, "rows": [{"id": "a" * 64, "name": "private-project-name", "role": "project", "running": True, "oom": False, "sample_available": True, "cpu_percent": 10, "memory_bytes": memory * 2, "memory_limit": 1024**3, "cpu_limit": 1, "read_bytes": 10, "write_bytes": 20, "pids": 2}]}}


class Clock:
    def __init__(self):
        self.now = 0
    def __call__(self):
        return self.now
    def wait(self, seconds):
        self.now += seconds


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "result.json"
        self.clock = Clock()

    def run_record(self, provider=None, **kwargs):
        return recording.record(provider or Mock(return_value=evidence()), output=self.output, clock=self.clock, wait=self.clock.wait, seconds=kwargs.pop("seconds", 15), interval=5, **kwargs)

    def test_validates_duration_and_activity_without_touching_files_or_echoing_input(self):
        for args in ((0, 5, "codex"), (3601, 10, "codex"), (True, 5, "codex"), (10, 1, "codex"), (10, 5, "socks5://user:private-password@host"), (10, 5, [])):
            with self.subTest(args=args):
                with self.assertRaises(SPXError) as failure:
                    recording.settings(*args)
                self.assertNotIn("private-password", str(failure.exception))
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_report_is_field_allowlisted_and_aliases_are_per_recording(self):
        raw = evidence()
        raw.update(password="private-password", project="C:/private-project", exit_ip="203.0.113.99")
        raw["app"][0].update(command_line="private-command", token="private-token")
        raw["containers"]["rows"][0].update(Env=["secret"], Mounts=["C:/private-project"])
        first = self.run_record(Mock(return_value=raw))
        serialized = self.output.read_text()
        for secret in ("private-", '"pid"', '"created"', "203.0.113.99", "a" * 64):
            self.assertNotIn(secret, serialized)
        self.assertEqual(len(first["samples"]), 3)
        self.assertEqual(first["samples"][0]["app"][0]["handle"], first["samples"][1]["app"][0]["handle"])
        second = self.run_record(Mock(return_value=raw))
        self.assertNotEqual(first["samples"][0]["app"][0]["handle"], second["samples"][0]["app"][0]["handle"])
        self.assertFalse(list(self.output.parent.glob("*.partial")))
        self.assertEqual(json.loads(self.output.read_text())["activity_evidence"], first["activity_evidence"])

    def test_reused_pid_is_not_merged_and_bad_counter_is_not_exported_as_number(self):
        codec = recording.Evidence()
        raw = evidence()
        first = codec.sample(raw, 0)
        raw["app"][0]["created"] += 1
        raw["app"][0]["cpu_percent"] = math.nan
        raw["host"]["memory_used"] = -1
        second = codec.sample(raw, 1)
        self.assertNotEqual(first["app"][0]["handle"], second["app"][0]["handle"])
        self.assertIsNone(second["app"][0]["cpu_percent"])
        self.assertIsNone(second["host"]["memory_used"])

    def test_increasing_memory_summary_uses_actual_samples_and_does_not_sum_wsl(self):
        provider = Mock(side_effect=[evidence(1000), evidence(2000), evidence(3000)])
        result = self.run_record(provider, activity="claude", source="gui")
        self.assertEqual(result["summary"]["app"]["memory_bytes"], {"count": 3, "min": 1000, "median": 2000, "max_sampled": 3000})
        self.assertEqual(result["summary"]["containers"]["memory_bytes"]["max_sampled"], 6000)
        self.assertEqual(result["summary"]["wsl"]["memory_bytes"]["max_sampled"], 5000)
        self.assertEqual(result["summary"]["app"]["cpu_percent"], {"count": 0})
        self.assertEqual(result["requested"]["activity"], "claude")

    def test_unavailable_data_and_exceptions_are_not_zero_resource_use(self):
        provider = Mock(side_effect=[PermissionError("private-password"), evidence(), RuntimeError("private-token")])
        result = self.run_record(provider)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["summary"]["host"]["memory_bytes"]["count"], 1)
        self.assertEqual(result["summary"]["containers"]["available_samples"], 1)
        self.assertNotIn("private-", self.output.read_text())

    def test_stopped_containers_are_verified_zero_and_truncated_scope_is_partial(self):
        raw = evidence()
        raw["containers"]["rows"] = []
        result = self.run_record(Mock(return_value=raw))
        self.assertEqual(result["summary"]["containers"]["memory_bytes"]["max_sampled"], 0)
        raw["containers"]["truncated"] = True
        result = self.run_record(Mock(return_value=raw))
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["summary"]["containers"]["memory_bytes"], {"count": 0})

    def test_missing_background_counters_do_not_become_a_complete_app_total(self):
        raw = evidence()
        raw["background_unavailable"] = 1
        result = self.run_record(Mock(return_value=raw))
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["summary"]["app"]["memory_bytes"], {"count": 0})
        self.assertEqual(result["samples"][0]["app"][0]["memory_bytes"], 1000)

    def test_user_cancel_keeps_only_completed_samples_and_public_stop_reason(self):
        cancel = threading.Event()
        def completed(raw, count, elapsed):
            cancel.set()
        result = self.run_record(cancel=cancel, on_sample=completed, stop_reason=lambda: "app_exit")
        self.assertEqual(result["end_reason"], "app_exit")
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(json.loads(self.output.read_text())["sample_count"], 1)

    def test_keyboard_interrupt_saves_report_for_cli_exit_130(self):
        result = self.run_record(Mock(side_effect=[evidence(), KeyboardInterrupt()]))
        self.assertEqual(result["end_reason"], "interrupted")
        self.assertEqual(result["sample_count"], 1)

    def test_sampling_never_catches_up_with_overlapping_queries(self):
        times = []
        def provider(cancel):
            times.append(self.clock())
            self.clock.now += 7
            return evidence()
        result = self.run_record(provider, seconds=30)
        self.assertEqual(times, [0, 12, 24])
        self.assertEqual([row["elapsed_seconds"] for row in result["samples"]], [7, 19, 31])

    def test_bounded_record_stops_queries_and_never_replaces_output_on_save_failure(self):
        provider = Mock(return_value=evidence())
        with patch.object(recording, "MAX_SAMPLES", 2):
            result = self.run_record(provider, seconds=30)
        self.assertEqual(result["end_reason"], "sample_limit")
        self.assertEqual(provider.call_count, 2)
        old = self.output.read_bytes()
        with patch.object(recording, "atomic_json", side_effect=PermissionError("private-path")):
            with self.assertRaises(recording.RecordingError) as failure:
                self.run_record()
        self.assertEqual(self.output.read_bytes(), old)
        self.assertEqual(failure.exception.report["sample_count"], 3)
        partial = list(self.output.parent.glob("*.partial"))
        self.assertEqual(len(partial), 1)
        lines = [json.loads(line) for line in partial[0].read_text().splitlines()]
        self.assertEqual([line["type"] for line in lines], ["header", "sample", "sample", "sample"])
        self.assertNotIn("private-path", str(failure.exception))

    def test_file_size_cap_finishes_cleanly_without_truncating_a_sample(self):
        raw = evidence()
        raw["containers"]["rows"] *= 8
        with patch.object(recording, "MAX_BYTES", 16384):
            result = self.run_record(Mock(return_value=raw), seconds=300)
        self.assertEqual(result["end_reason"], "size_limit")
        self.assertLessEqual(self.output.stat().st_size, 16384)
        json.loads(self.output.read_text())


if __name__ == "__main__":
    unittest.main()
