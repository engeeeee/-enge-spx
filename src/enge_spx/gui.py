"""Qt desktop entry point; engine work never runs in the GUI thread."""
import os
import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from . import __version__
from .gui_diagnostics import GuiDiagnostics, log
from .platform_ui import WindowInstance, prepare_windows
from .state import SPXError
from .ui import style
from .ui.controller import Controller, size_text
from .ui.window import Window as App


def launch(store, smoke=False):
    with GuiDiagnostics(store.home) as report:
        try:
            _launch(store, report, smoke)
        except Exception as error:
            report.capture("gui-launch-error", type(error), error, error.__traceback__)
            raise SPXError(f"ENGE SPX 启动异常。请保留诊断日志：{report.directory}") from error


def _launch(store, report, smoke):
    started = time.perf_counter()
    prepare_windows(dpi=False)
    instance = WindowInstance(store.home, legacy=store.legacy)
    if not instance.acquire():
        log.info("gui-duplicate-instance-exit")
        return
    window = None
    try:
        if os.name != "nt" and not any(os.environ.get(key) for key in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM")):
            raise SPXError("未检测到图形会话，请在桌面环境启动界面。")
        app = QApplication.instance() or QApplication(["ENGE SPX"])
        app.setApplicationName("ENGE SPX")
        app.setOrganizationName("engeeeee")
        style.apply(app)
        def relocated(new_store):
            nonlocal instance
            replacement = WindowInstance(new_store.home, legacy=new_store.legacy)
            if not replacement.acquire():
                return False
            replacement.register_hwnd(int(window.winId()))
            instance.close()
            instance = replacement
            return True
        controller = Controller(store, report, relocated)
        window = App(controller)
        window.closed.connect(app.quit)
        if os.name == "nt" and window.install_tray():
            app.setQuitOnLastWindowClosed(False)
            log.info("gui-tray-enabled close-action=hide")
        report.attach(window)
        report.observe(window)
        area = app.primaryScreen().availableGeometry()
        minimum_width = min(700, max(400, area.width() - 24))
        minimum_height = min(480, max(320, area.height() - 24))
        window.setMinimumSize(minimum_width, minimum_height)
        window.resize(min(1220, area.width() - 24), min(860, area.height() - 24))
        window.move(area.center() - window.rect().center())
        window.show()
        instance.register_hwnd(int(window.winId()))
        log.info("gui-window-visible toolkit=Qt scale=%s", window.devicePixelRatioF())
        if smoke:
            def painted():
                store.write("ui-smoke.json", {"app": window.windowTitle(), "version": __version__, "toolkit": "Qt", "first_paint_ms": round((time.perf_counter() - started) * 1000), "icons": not window.windowIcon().isNull(), "custom_frame": bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint), "native_frame": os.name == "nt" and app.platformName() == "windows", "brand_visible": window.titlebar.caption.text().startswith("ENGE SPX") if window.compact else window.brand_label.width() >= window.brand_label.sizeHint().width()})
                QTimer.singleShot(400, window.finish_close)
            QTimer.singleShot(100, painted)
        else:
            QTimer.singleShot(500, lambda: controller.check_docker(False))
            QTimer.singleShot(6000, lambda: controller.check_updates(True))
        app.exec()
        log.info("gui-event-loop-return")
    finally:
        if window is not None:
            window.finish_close()
        instance.close()
