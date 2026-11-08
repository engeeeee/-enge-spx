import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from enge_spx.downloads import DownloadPaused
from enge_spx.engine import Engine
from enge_spx.startup import (
    DockerConfigurationError, DockerContextUnavailable, DockerUnavailable,
    StartupIssue, diagnostics, ensure_docker, launch_desktop, prepare_workspace,
)
from enge_spx.state import SPXError, Store


INFO = {"docker": "29.0.0", "architecture": "x86_64", "context": "desktop-linux"}


class Clock:
    def __init__(self):
        self.value = 0

    def monotonic(self):
        return self.value

    def sleep(self, delay):
        self.value += delay


class StartupCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name) / "private")
        self.engine = Mock()
        self.engine.store = self.store
        self.engine.docker.executable = "docker.exe"
        self.engine.docker.context = "desktop-linux"
        self.engine.doctor.return_value = INFO
        self.clock = Clock()
        for name in ("monotonic", "sleep"):
            mock = patch("enge_spx.startup.time." + name, getattr(self.clock, name))
            mock.start()
            self.addCleanup(mock.stop)


class StartupTests(StartupCase):
    def test_running_engine_is_reused_without_launch(self):
        with patch("enge_spx.startup.launch_desktop") as launch:
            self.assertEqual(ensure_docker(self.engine, windows=True), INFO)
        launch.assert_not_called()

    def test_stopped_engine_launches_once_and_waits_for_real_readiness(self):
        self.engine.doctor.side_effect = [DockerUnavailable("starting"), DockerUnavailable("starting"), INFO]
        progress = []
        with patch("enge_spx.startup.launch_desktop") as launch:
            self.assertEqual(ensure_docker(self.engine, progress.append, windows=True), INFO)
        launch.assert_called_once_with(self.engine.docker)
        self.assertEqual(self.engine.doctor.call_count, 3)
        self.assertIn("docker_wait", [v["stage"] for v in progress])
        self.assertEqual(progress[-1]["stage"], "docker_ready")

    def test_desktop_context_can_appear_during_first_initialization(self):
        self.engine.doctor.side_effect = [DockerContextUnavailable("missing"), INFO]
        with patch("enge_spx.startup.launch_desktop") as launch:
            ensure_docker(self.engine, windows=True)
        launch.assert_called_once()
        self.assertEqual(self.engine.docker.context, "desktop-linux")

    def test_invalid_context_and_configuration_do_not_launch_or_switch_engine(self):
        for error, context, code in [(DockerContextUnavailable("missing"), "custom", "docker_context"), (DockerConfigurationError("use Linux containers"), "desktop-linux", "docker_configuration")]:
            with self.subTest(code=code), patch("enge_spx.startup.launch_desktop") as launch:
                self.engine.docker.context = context
                self.engine.doctor.side_effect = error
                with self.assertRaises(StartupIssue) as caught:
                    ensure_docker(self.engine, windows=True)
                self.assertEqual(caught.exception.code, code)
                launch.assert_not_called()
                self.assertEqual(self.engine.docker.context, context)

    def test_missing_cli_and_disabled_automatic_start_are_actionable(self):
        self.engine.docker.executable = None
        with self.assertRaises(StartupIssue) as caught:
            ensure_docker(self.engine, windows=True)
        self.assertEqual(caught.exception.code, "docker_missing")
        self.engine.docker.executable = "docker.exe"
        self.engine.doctor.side_effect = DockerUnavailable("stopped")
        with patch("enge_spx.startup.launch_desktop") as launch:
            for windows, auto_start in [(True, False), (False, True)]:
                with self.assertRaises(StartupIssue) as caught:
                    ensure_docker(self.engine, windows=windows, auto_start=auto_start)
                self.assertEqual(caught.exception.code, "docker_stopped")
        launch.assert_not_called()

    def test_wait_has_deadline_and_never_kills_desktop(self):
        self.engine.doctor.side_effect = DockerUnavailable("starting")
        with patch("enge_spx.startup.launch_desktop") as launch:
            with self.assertRaises(StartupIssue) as caught:
                ensure_docker(self.engine, windows=True, timeout=4)
        self.assertEqual(caught.exception.code, "docker_timeout")
        launch.assert_called_once()
        self.assertEqual(self.clock.value, 4)
        self.engine.stop.assert_not_called()

    def test_cancellation_stops_wait_without_stopping_desktop_or_deleting_data(self):
        cancel = threading.Event()
        self.store.write("nodes.json", [{"password": "preserve"}])
        self.engine.doctor.side_effect = DockerUnavailable("starting")
        def progress(value):
            if value["stage"] == "docker_wait":
                cancel.set()
        with patch("enge_spx.startup.launch_desktop") as launch:
            # Advance fake time rather than sleeping on the real Event.
            with patch.object(cancel, "wait", side_effect=self.clock.sleep):
                with self.assertRaises(DownloadPaused):
                    ensure_docker(self.engine, progress, cancel, windows=True)
        launch.assert_called_once()
        self.engine.stop.assert_not_called()
        self.assertEqual(self.store.read("nodes.json"), [{"password": "preserve"}])

    def test_management_cli_is_unscoped_and_falls_back_for_older_desktop(self):
        self.engine.docker.environment.return_value = {"DOCKER_CONFIG": "preserved"}
        self.engine.docker.desktop_app.return_value = Path("D:/Docker App/Docker Desktop.exe")
        with patch("enge_spx.startup.subprocess.run", return_value=subprocess.CompletedProcess([], 2)) as run, patch("enge_spx.startup.subprocess.Popen") as launch:
            self.assertEqual(launch_desktop(self.engine.docker), "application")
        self.assertNotIn("--context", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["env"], {"DOCKER_CONFIG": "preserved"})
        self.assertEqual(launch.call_args.args[0], ["D:/Docker App/Docker Desktop.exe"])
        with patch("enge_spx.startup.subprocess.run", return_value=subprocess.CompletedProcess([], 0)), patch("enge_spx.startup.subprocess.Popen") as launch:
            self.assertEqual(launch_desktop(self.engine.docker), "cli")
        launch.assert_not_called()

    def test_existing_images_are_reused_and_node_configuration_is_next(self):
        with patch("enge_spx.startup.ensure_docker", return_value=INFO):
            result = prepare_workspace(self.engine)
        self.assertEqual(result["phase"], "needs_configuration")
        self.engine.install.assert_not_called()
        self.engine.install_prebuilt.assert_not_called()
        self.engine.confirm.assert_not_called()

    def test_first_install_is_verified_and_source_build_requires_explicit_choice(self):
        for source in (False, True):
            with self.subTest(source=source), patch("enge_spx.startup.ensure_docker", return_value=INFO):
                self.engine.reset_mock()
                self.engine.image_ids.side_effect = [SPXError("not installed"), {"gateway": "verified"}]
                result = prepare_workspace(self.engine, check=False, source=source)
                self.assertEqual(result["phase"], "prepared")
                self.assertEqual(self.engine.image_ids.call_count, 2)
                chosen = self.engine.install if source else self.engine.install_prebuilt
                other = self.engine.install_prebuilt if source else self.engine.install
                chosen.assert_called_once()
                other.assert_not_called()
                self.engine.confirm.assert_not_called()

    def test_opening_app_can_inspect_without_downloading(self):
        self.engine.image_ids.side_effect = SPXError("missing")
        with patch("enge_spx.startup.ensure_docker", return_value=INFO):
            result = prepare_workspace(self.engine, install=False, check=False)
        self.assertEqual(result["phase"], "needs_runtime")
        self.engine.install_prebuilt.assert_not_called()

    def test_explicit_source_build_is_not_skipped_for_existing_images(self):
        with patch("enge_spx.startup.ensure_docker", return_value=INFO):
            prepare_workspace(self.engine, source=True, check=False)
        self.engine.install.assert_called_once()
        self.engine.install_prebuilt.assert_not_called()

    def test_connection_check_returns_review_and_never_accepts_exit_automatically(self):
        self.store.write("settings.json", {"selected": "landing"})
        self.engine.check.return_value = {"ip": "192.0.2.1"}
        with patch("enge_spx.startup.ensure_docker", return_value=INFO):
            result = prepare_workspace(self.engine)
        self.assertEqual(result["phase"], "review")
        self.assertEqual(result["evidence"], {"ip": "192.0.2.1"})
        self.engine.confirm.assert_not_called()

    def test_existing_ready_environment_is_revalidated(self):
        self.store.write("settings.json", {"selected": "landing"})
        self.store.write("runtime.json", {"phase": "ready"})
        self.engine.ready.return_value = {"phase": "ready", "evidence": {"ip": "192.0.2.1"}}
        with patch("enge_spx.startup.ensure_docker", return_value=INFO):
            result = prepare_workspace(self.engine)
        self.assertEqual(result["phase"], "ready")
        self.assertEqual(result["evidence"], {"ip": "192.0.2.1"})
        self.engine.check.assert_not_called()
        self.engine.confirm.assert_not_called()

    def test_installed_context_cannot_change_during_bootstrap(self):
        self.store.write("images.json", {"gateway": "existing"})
        with patch("enge_spx.startup.ensure_docker") as ensure:
            with self.assertRaises(StartupIssue):
                prepare_workspace(self.engine, ("", "Etc/UTC", "different", {"enabled": False}))
        ensure.assert_not_called()
        self.assertEqual(self.engine.docker.context, "desktop-linux")

    def test_diagnostics_excludes_accounts_routes_paths_and_arbitrary_error_messages(self):
        settings = self.store.settings()
        settings.update({"projects": ["C:/Private/Secret"], "relay": {"enabled": True, "mode": "local", "url": "socks5://secret-user:secret-password@127.0.0.1:1080"}})
        self.store.write("settings.json", settings)
        self.store.write("nodes.json", [{"password": "secret-node"}])
        self.store.write("runtime.json", {"phase": "stopped", "reason": "secret-reason", "evidence": {"ip": "192.0.2.99"}})
        self.store.write("browser-token.json", {"token": "secret-browser"})
        value = diagnostics(self.store, {**INFO, "data": str(self.store.home)}, "docker_timeout")
        serialized = json.dumps(value)
        for private in ("secret-", "C:/Private", "192.0.2.99", str(self.store.home)):
            self.assertNotIn(private, serialized)
        self.assertEqual(value["startup_error"], "docker_timeout")


class DoctorTests(StartupCase):
    def doctor(self, context, info):
        engine = Engine(self.store)
        engine.docker = Mock(executable="docker.exe", context="desktop-linux")
        engine.docker.run.side_effect = [json.dumps(context), json.dumps(info)]
        return engine

    def test_configuration_errors_are_not_mistaken_for_startup_delay(self):
        local = [{"Endpoints": {"docker": {"Host": "npipe:////./pipe/dockerDesktopLinuxEngine"}}}]
        linux = {"OSType": "linux", "Architecture": "x86_64", "ServerVersion": "29.0.0"}
        cases = [({}, linux), ([], linux), ([{}], linux), ([{"Endpoints": None}], linux), ([{"Endpoints": {"docker": {"Host": "tcp://remote:2375"}}}], linux), (local, {**linux, "OSType": "windows"}), (local, {**linux, "Architecture": "unsupported"}), (local, {**linux, "ServerVersion": "27.5"})]
        for context, info in cases:
            with self.subTest(context=context, info=info):
                engine = self.doctor(context, info)
                with self.assertRaises(DockerConfigurationError):
                    engine.doctor(timeout=2)
                self.assertFalse(any("use" in c.args or "switch" in c.args for c in engine.docker.run.call_args_list))

    def test_unavailable_context_and_engine_can_retry(self):
        engine = self.doctor([], {})
        engine.docker.run.side_effect = SPXError("not ready")
        with self.assertRaises(DockerContextUnavailable):
            engine.doctor(timeout=2)
        engine.docker.run.side_effect = [json.dumps([{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]), SPXError("not ready")]
        with self.assertRaises(DockerUnavailable):
            engine.doctor(timeout=2)
        self.assertEqual(engine.docker.run.call_args.kwargs["timeout"], 2)


@unittest.skipUnless(os.name == "nt", "Native Windows Desktop subprocess startup")
class WindowsDesktopTests(unittest.TestCase):
    def test_custom_drive_layout_legacy_cli_and_delayed_linux_readiness(self):
        system = Path(os.environ["SystemRoot"])
        compiler = next((p for p in [system / "Microsoft.NET/Framework64/v4.0.30319/csc.exe", system / "Microsoft.NET/Framework/v4.0.30319/csc.exe"] if p.is_file()), None)
        self.assertIsNotNone(compiler, "Windows CI must provide the .NET Framework compiler for this integration test")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "FakeDocker.cs"
            source.write_text(r'''
using System;
using System.IO;
class FakeDocker {
    static int Main(string[] args) {
        string marker = Environment.GetEnvironmentVariable("SPX_TEST_DOCKER_MARKER");
        string name = Path.GetFileName(Environment.GetCommandLineArgs()[0]);
        if (name == "Docker Desktop.exe") {
            File.AppendAllText(marker + ".launches", "launch\n");
            File.WriteAllText(marker, "started");
            return 0;
        }
        string command = String.Join(" ", args);
        File.AppendAllText(marker + ".commands", command + "\n");
        if (command.StartsWith("desktop start ")) return 2;
        if (!command.StartsWith("--context desktop-linux ")) return 3;
        if (command.Contains(" context inspect ")) {
            Console.WriteLine("[{\"Endpoints\":{\"docker\":{\"Host\":\"npipe:////./pipe/dockerDesktopLinuxEngine\"}}}]");
            return 0;
        }
        if (command.Contains(" info ")) {
            if (!File.Exists(marker)) return 1;
            if (!File.Exists(marker + ".waiting")) {
                File.WriteAllText(marker + ".waiting", "wait");
                return 1;
            }
            Console.WriteLine("{\"OSType\":\"linux\",\"ServerVersion\":\"29.0.0\",\"Architecture\":\"x86_64\"}");
            return 0;
        }
        return 4;
    }
}''', encoding="utf-8")
            cli = base / "Docker App/resources/bin/docker.exe"
            cli.parent.mkdir(parents=True)
            subprocess.run([str(compiler), "/nologo", "/target:exe", "/out:" + str(cli), str(source)], check=True, capture_output=True)
            desktop = base / "Docker App/Docker Desktop.exe"
            shutil.copyfile(cli, desktop)
            marker = base / "marker"
            engine = Engine(Store(base / "data"))
            engine.docker.executable = str(cli)
            progress = []
            with patch.dict(os.environ, {"SPX_TEST_DOCKER_MARKER": str(marker)}):
                result = ensure_docker(engine, progress.append, windows=True, timeout=15)
            self.assertEqual(result["docker"], "29.0.0")
            self.assertEqual(Path(str(marker) + ".launches").read_text().splitlines(), ["launch"])
            commands = Path(str(marker) + ".commands").read_text().splitlines()
            self.assertEqual(sum(c.startswith("desktop start ") for c in commands), 1)
            self.assertTrue(all(c.startswith(("desktop start ", "--context desktop-linux ")) for c in commands))
            self.assertTrue(any(p["stage"] == "docker_wait" for p in progress))
            self.assertFalse(any("context use" in c or "engine switch" in c for c in commands))


if __name__ == "__main__":
    unittest.main()
