import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
from enge_spx.engine import Engine
from enge_spx.state import Store
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window
from enge_spx.workspace_profiles import FILE


class WorkspaceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "data")
        self.project = self.root / "project"
        self.project.mkdir()
        self.identity = Engine(self.store).create_workspace_profile("独立身份")["profile"]
        self.controller = Controller(self.store)
        self.controller.project.set(str(self.project))
        self.window = Window(self.controller)
        self.window.show()
        self.window.show_page("workspace")
        self.addCleanup(self.window.finish_close)

    def wait(self):
        for _ in range(100):
            QTest.qWait(20)
            time.sleep(.005)
            if not self.controller.busy:
                return
        self.fail("Workspace operation did not finish")

    def test_selection_does_not_mutate_or_launch_and_apply_captures_identity(self):
        c = self.controller
        box = self.window.workspace_profile_box
        box.setCurrentIndex(box.findData(self.identity))
        c.workspace_access.set("ro")
        self.assertEqual(self.store.read(FILE)["selected"], "shared")
        self.assertFalse(c.workspace_selection_matches())
        with patch.object(c, "notify") as notice, patch.object(c, "run") as run:
            c.open_terminal("codex")
            notice.assert_called_once()
            run.assert_not_called()
        c.apply_workspace()
        self.wait()
        self.assertEqual(self.store.read(FILE)["selected"], self.identity)
        self.assertTrue(c.workspace_selection_matches())
        c.settings_match = Mock(return_value=True)
        with patch.object(c, "run") as run:
            c.open_terminal("codex")
            engine = Mock()
            run.call_args.args[0](engine)
        engine.terminal.assert_called_once_with(str(self.project.resolve()), "codex", expected_workspace=(self.identity, "ro"))

    def test_another_project_requires_explicit_binding_and_never_inherits_accounts(self):
        c = self.controller
        c.workspace_profile.set(self.identity)
        c.workspace_access.set("ro")
        c.apply_workspace()
        self.wait()
        other = self.root / "second"
        other.mkdir()
        c.project.set(str(other))
        self.assertEqual(c.workspace_profile.get(), self.identity)
        self.assertFalse(c.workspace_selection_matches())
        self.assertIn("待应用", c.workspace_status.get())

    def test_readwrite_requires_explicit_apply_and_create_stays_pending(self):
        c = self.controller
        c.workspace_profile.set(self.identity)
        c.workspace_access.set("ro")
        c.apply_workspace()
        self.wait()
        c.workspace_access.set("rw")
        self.assertFalse(c.workspace_selection_matches())
        self.assertEqual(next(iter(self.store.read(FILE)["projects"].values()))["access"], "ro")
        c.create_workspace("另一身份")
        self.wait()
        self.assertNotEqual(c.workspace_profile.get(), self.identity)
        self.assertEqual(self.store.read(FILE)["selected"], self.identity)
        self.assertEqual(c.workspace_access.get(), "ro")

    def test_unavailable_config_has_no_shared_fallback_in_gui(self):
        self.store.write(FILE, None)
        controller = Controller(self.store)
        window = Window(controller)
        self.addCleanup(window.finish_close)
        window.show_page("workspace")
        self.assertIsNone(controller.workspace_config)
        self.assertEqual(window.workspace_profile_box.currentData(), "")
        self.assertFalse(controller.workspace_selection_matches())

    def test_editing_project_path_does_not_resolve_or_probe_network_share(self):
        with patch.object(self.store, "project", side_effect=AssertionError("GUI keystroke resolved a path")):
            self.controller.project.set("\\\\server\\share\\project")
            self.controller.project.set("D:\\new project")

    def test_browser_uses_captured_profile_and_never_an_unapplied_choice(self):
        c = self.controller
        c.workspace_profile.set(self.identity)
        with patch.object(c, "notify"), patch.object(c, "run") as run:
            self.assertFalse(c.open_workspace_browser())
            run.assert_not_called()
        c.workspace_profile.set("shared")
        with patch.object(c, "run") as run:
            c.open_workspace_browser()
            c.workspace_profile.set(self.identity)
            engine = Mock()
            run.call_args.args[0](engine)
        engine.browser.assert_called_once_with(expected_profile="shared")

    def test_create_dialog_reaches_real_worker_without_automatically_switching(self):
        def submit():
            dialog = self.app.activeModalWidget()
            dialog.findChild(QLineEdit).setText("从窗口创建")
            next(item for item in dialog.findChildren(QPushButton) if item.text() == "创建空白身份").click()
        QTimer.singleShot(30, submit)
        self.window.new_workspace_profile()
        self.wait()
        self.assertIn("从窗口创建", self.controller.workspace_config["profiles"].values())
        self.assertEqual(self.store.read(FILE)["selected"], "shared")
        self.assertFalse(self.controller.workspace_selection_matches())

    def test_network_page_is_lazy_readonly_and_exports_the_observed_report(self):
        c = self.controller
        with patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Opening a page queried Docker")):
            self.window.show_page("network")
            QTest.qWait(30)
        self.assertIsNone(c.network_report)
        report = {"schema": 1, "status": "partial", "objects": {"browser": {"status": "not_running"}}}
        with patch("enge_spx.engine.Engine.network_diagnostics", return_value=report):
            c.check_network()
            self.wait()
        self.assertEqual(c.network_report, report)
        self.assertIn("部分检查", c.network_summary.get())
        target = self.root / "network-report.json"
        c.export_network_report(target)
        self.wait()
        import json
        self.assertEqual(json.loads(target.read_text()), report)


if __name__ == "__main__":
    unittest.main()
