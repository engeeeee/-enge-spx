import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from enge_spx.docker_env import local_endpoint
from enge_spx.engine import Engine
from enge_spx.resource_monitor import containers, sampling_target
from enge_spx.startup import DockerConfigurationError
from enge_spx.state import Store


class LocalResourceContextTests(unittest.TestCase):
    def test_standard_desktop_and_local_unix_endpoints_remain_compatible(self):
        for value in ("unix:///var/run/docker.sock", "unix:///run/user/1000/docker.sock", "npipe:////./pipe/dockerDesktopLinuxEngine", "npipe:////./pipe/docker_engine", "npipe://./pipe/docker_engine"):
            with self.subTest(value=value):
                self.assertTrue(local_endpoint(value))

    def test_remote_pipes_socket_authorities_and_tcp_are_not_local_ipc(self):
        for value in ("ssh://user:private-password@example", "tcp://127.0.0.1:2375", "unix://remote/socket", "unix:////remote/socket", "npipe:////server/pipe/docker_engine", "npipe://server/pipe/docker_engine", "unix:///socket?proxy=private", "\nunix:///var/run/docker.sock", None):
            with self.subTest(value=value):
                self.assertFalse(local_endpoint(value))

    def test_resource_query_rejects_remote_context_before_ps_info_or_stats(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(Store(Path(folder)))
            engine.docker = Mock()
            engine.docker.run.return_value = json.dumps([{"Endpoints": {"docker": {"Host": "ssh://user:private-password@example"}}}])
            with self.assertRaises(DockerConfigurationError) as error:
                containers(engine)
            self.assertNotIn("private-password", str(error.exception))
            engine.docker.run.assert_called_once_with("context", "inspect", engine.docker.context, timeout=6)

    def test_sampling_target_reads_only_matching_public_context_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            def read(name, default=None):
                self.assertEqual(name, "controller-context.json")
                return {"instance": store.instance, "context": "chosen-local"}
            with patch.object(store, "settings", side_effect=AssertionError("Read proxy settings")), patch.object(store, "read", side_effect=read), patch("enge_spx.engine.Engine", side_effect=AssertionError("Full workspace engine created")):
                target = sampling_target(store)
            self.assertTrue(target.ready)
            self.assertEqual(target.docker.context, "chosen-local")
            with patch.object(store, "read", return_value={"instance": "another-instance", "context": "remote"}):
                self.assertFalse(sampling_target(store).ready)


if __name__ == "__main__":
    unittest.main()
