import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QPushButton
from enge_spx.state import Store
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window


class ExitRecoveryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.store.write("runtime.json", {"phase": "stopped"})
        self.c = Controller(self.store)
        self.c.exit_stage = "failed"
        self.c.exit_workspace_stopped = True
        self.c.exit_docker = Mock()
        self.c.desktop_exit_supported = self.c.saved_close_desktop = True
        self.window = Window(self.c)
        self.window.show()
        self.addCleanup(self.window.finish_close)

    def select(self, name=None):
        seen = []
        def choose():
            dialog = self.app.activeModalWidget()
            if dialog is None:
                seen.append("missing")
                return
            seen.append(dialog.objectName())
            cancel = dialog.findChild(QPushButton, "desktop-exit-return")
            seen.append(cancel is not None and cancel.isDefault())
            if name:
                dialog.findChild(QPushButton, name).click()
            else:
                QTest.keyClick(dialog, Qt.Key.Key_Return)
        QTimer.singleShot(30, choose)
        self.window.show_exit_error("等待 Docker Desktop 正常关闭超时；未强制结束进程。")
        self.assertEqual(seen, ["desktop-exit-recovery", True])

    def test_return_is_default_and_does_not_exit_or_change_preference(self):
        with unittest.mock.patch.object(self.c, "request_exit") as retry:
            self.select()
            retry.assert_not_called()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.c.saved_close_desktop)

    def test_app_only_button_uses_guarded_one_time_exit(self):
        closed = QSignalSpy(self.c.close_requested)
        self.select("desktop-exit-app-only")
        self.assertEqual(closed.count(), 1)
        self.assertTrue(self.c.exit_skip_desktop)
        self.assertTrue(self.c.saved_close_desktop)
        self.assertFalse(self.c.exit_desktop_done)

    def test_retry_button_reuses_normal_exit(self):
        with unittest.mock.patch.object(self.c, "request_exit") as retry:
            self.select("desktop-exit-retry")
            retry.assert_called_once_with()

    def test_workspace_failure_does_not_offer_app_only_recovery(self):
        self.c.exit_workspace_stopped = False
        seen = []
        def inspect():
            dialog = self.app.activeModalWidget()
            try:
                seen.append(dialog.objectName())
                seen.append(dialog.findChild(QPushButton, "desktop-exit-app-only") is None)
                seen.append(dialog.findChild(QPushButton, "workspace-exit-return").isDefault())
            finally:
                dialog.reject()
        QTimer.singleShot(30, inspect)
        self.window.show_exit_error("工作区未停止")
        self.assertEqual(seen, ["workspace-exit-recovery", True, True])
        self.assertIsNone(self.app.activeModalWidget())
        self.assertFalse(self.c.exit_without_desktop_once())

    def test_workspace_failure_copy_is_json_and_does_not_close_or_contact_docker(self):
        self.c.exit_workspace_stopped = False
        self.c.exit_diagnostics = {"schema": 1, "workspace_stop_verified": False, "checks": [{"stage": "wsl2_configuration", "result": "not_confirmed"}]}
        copied = []
        def inspect():
            dialog = self.app.activeModalWidget()
            try:
                dialog.findChild(QPushButton, "workspace-exit-copy").click()
                copied.append(QApplication.clipboard().text())
                copied.append(dialog.isVisible())
            finally:
                dialog.reject()
        QTimer.singleShot(30, inspect)
        with unittest.mock.patch("enge_spx.engine.Docker.run", side_effect=AssertionError("Copy must not contact Docker")):
            self.window.show_exit_error("Docker 操作失败：missing engine pipe")
        report = json.loads(copied[0])
        self.assertEqual(report["app"], "ENGE SPX")
        self.assertIn("version", report)
        self.assertFalse(report["last_exit"]["workspace_stop_verified"])
        self.assertTrue(copied[1])

    def test_workspace_failure_retry_is_the_default_stopped_workspace_exit(self):
        self.c.exit_workspace_stopped = False
        def inspect():
            self.app.activeModalWidget().findChild(QPushButton, "workspace-exit-retry").click()
        QTimer.singleShot(30, inspect)
        with unittest.mock.patch.object(self.c, "request_exit") as retry:
            self.window.show_exit_error("missing engine pipe")
        retry.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
