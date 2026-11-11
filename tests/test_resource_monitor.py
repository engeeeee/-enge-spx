import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from enge_spx.engine import Engine
from enge_spx.process_metrics import Sampler, process, system, tracked
from enge_spx.resource_monitor import Monitor, byte_count, containers
from enge_spx.state import SPXError, Store


class ProcessTests(unittest.TestCase):
    def test_real_current_process_and_host_counters_need_no_elevation(self):
        value = process(os.getpid())
        self.assertIsNotNone(value)
        self.assertGreater(value["memory_bytes"], 0)
        self.assertGreater(value["created"], 0)
        self.assertGreaterEqual(value["cpu_seconds"], 0)
        counters = system()
        self.assertGreater(counters["memory_total"], 0)
        self.assertLessEqual(counters["memory_used"], counters["memory_total"])
        self.assertGreaterEqual(counters["cpu_total"], counters["cpu_idle"])
        self.assertIsNone(process(-1))

    def test_cpu_delta_is_one_core_percent_and_reused_pid_has_no_old_delta(self):
        sampler = Sampler()
        def sample(created, cpu):
            return {"pid": 123, "created": created, "cpu_seconds": cpu, "memory_bytes": 100}
        with patch("enge_spx.process_metrics.process", side_effect=[sample(1, 2), sample(1, 4), sample(2, 1)]), patch("enge_spx.process_metrics.time.monotonic", side_effect=[1, 3, 5]):
            self.assertIsNone(sampler.sample(123)["cpu_percent"])
            self.assertEqual(sampler.sample(123)["cpu_percent"], 100)
            self.assertIsNone(sampler.sample(123)["cpu_percent"])

    def test_tracking_contains_only_public_counters_and_cleans_up_even_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                with tracked(store, "guard"):
                    path = next((store.home / "processes").glob("*.json"))
                    value = json.loads(path.read_text())
                    self.assertEqual(set(value), {"schema", "action", "pid", "created"})
                    raise RuntimeError("fixture")
            self.assertFalse(list((store.home / "processes").glob("*.json")))
            with patch.object(store, "write", side_effect=PermissionError("denied")):
                with tracked(store, "guard"):
                    self.assertTrue(True, "Metric registration must not stop a safety process")

    @unittest.skipUnless(os.name == "nt", "Real Win32 process handles")
    def test_repeated_native_queries_close_process_handles(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", winmode=0x00000800)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.GetCurrentProcess()
        before, after = wintypes.DWORD(), wintypes.DWORD()
        process(os.getpid())
        self.assertTrue(kernel.GetProcessHandleCount(handle, ctypes.byref(before)))
        for _ in range(100):
            self.assertIsNotNone(process(os.getpid()))
        self.assertTrue(kernel.GetProcessHandleCount(handle, ctypes.byref(after)))
        self.assertLessEqual(after.value - before.value, 2)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        self.engine = Engine(self.store)
        self.engine.docker = Mock()
        context = patch("enge_spx.resource_monitor.require_local_context")
        context.start()
        self.addCleanup(context.stop)
        self.identifier = "a" * 64

    def fixture(self, owner=None, running=True):
        row = {"id": self.identifier, "name": "/fixture", "role": "project", "owner": owner or self.store.instance, "running": running, "oom": False, "memory_limit": 1024**3, "nano_cpus": 0, "period": 100000, "quota": 50000}
        statistics = {"ID": self.identifier, "CPUPerc": "12.5%", "MemUsage": "10MiB / 1GiB", "BlockIO": "1kB / 2KiB", "PIDs": "3"}
        self.engine.docker.run.side_effect = [self.identifier, json.dumps(row), json.dumps(statistics)]
        return row

    def test_scoped_stats_convert_units_and_never_request_secrets_or_all_containers(self):
        self.fixture()
        result = containers(self.engine)
        row = result["rows"][0]
        self.assertEqual(row["memory_bytes"], 10 * 1024**2)
        self.assertEqual(row["cpu_percent"], 12.5)
        self.assertEqual(row["cpu_limit"], .5)
        self.assertEqual((row["read_bytes"], row["write_bytes"]), (1000, 2048))
        calls = self.engine.docker.run.call_args_list
        self.assertIn("label=" + self.engine.owner + "=" + self.store.instance, calls[0].args)
        self.assertNotIn("Env", calls[1].args[3])
        self.assertNotIn("Mounts", calls[1].args[3])
        self.assertEqual(calls[-1].args[-1], self.identifier)
        self.assertNotIn("inspect", calls[-1].args)

    def test_empty_or_stopped_resources_never_issue_global_stats(self):
        self.engine.docker.run.return_value = ""
        self.assertEqual(containers(self.engine)["rows"], [])
        self.engine.docker.run.assert_called_once()
        self.engine.docker.run.reset_mock()
        self.fixture(running=False)
        self.assertFalse(containers(self.engine)["rows"][0]["sample_available"])
        self.assertEqual(self.engine.docker.run.call_count, 2)

    def test_foreign_owner_rejects_before_stats(self):
        self.fixture(owner="foreign")
        with self.assertRaises(SPXError):
            containers(self.engine)
        self.assertEqual(self.engine.docker.run.call_count, 2)

    def test_cancelled_sample_does_not_start_another_docker_command(self):
        cancel = threading.Event()
        def first(*args, **kwargs):
            cancel.set()
            return self.identifier
        self.engine.docker.run.side_effect = first
        with self.assertRaisesRegex(SPXError, "已取消"):
            containers(self.engine, cancel)
        self.engine.docker.run.assert_called_once()

    def test_host_snapshot_does_not_contact_or_start_docker_when_not_ready(self):
        with patch("enge_spx.process_metrics.desktop_processes", return_value=[]):
            snapshot = Monitor().snapshot(self.engine, False)
        self.engine.docker.run.assert_not_called()
        self.assertFalse(snapshot["containers"]["available"])
        self.assertEqual(snapshot["app"][0]["pid"], os.getpid())
        self.assertNotIn("settings", snapshot)

    def test_reused_background_pid_cannot_be_attributed_to_application(self):
        current = process(os.getpid())
        self.store.write(f"processes/guard-{os.getpid()}.json", {"schema": 1, "action": "guard", "pid": os.getpid(), "created": current["created"] - 1})
        with patch("enge_spx.process_metrics.desktop_processes", return_value=[]):
            snapshot = Monitor().snapshot(self.engine)
        self.assertEqual(len(snapshot["app"]), 1)
        self.assertEqual(snapshot["background_unavailable"], 1)

    def test_byte_counter_rejects_invalid_input_without_echoing_it(self):
        self.assertEqual(byte_count("1.5GiB"), 1610612736)
        with self.assertRaisesRegex(ValueError, "Invalid Docker byte count"):
            byte_count("synthetic-password")


if __name__ == "__main__":
    unittest.main()
