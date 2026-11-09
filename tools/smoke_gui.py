"""Exercise the real native interface without launching the host's Docker."""
from pathlib import Path
import faulthandler
import json
import os
import tempfile
import threading
import time
from unittest.mock import patch

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from enge_spx.downloads import DownloadPaused
from enge_spx.nodes import parse_nodes
from enge_spx.state import Store
from enge_spx.ui import style
from enge_spx.ui.controller import Controller
from enge_spx.ui.widgets import confirm
from enge_spx.ui.window import Window, NAMES

faulthandler.dump_traceback_later(75, exit=True)
app = QApplication.instance() or QApplication([])
style.apply(app)


def settle(controller):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if not controller.busy else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    timer.start()
    deadline.start(15000)
    if controller.busy:
        loop.exec()
    timer.stop()
    deadline.stop()
    if controller.busy:
        faulthandler.dump_traceback()
    assert not controller.busy, "GUI worker did not finish"
    QTest.qWait(60)


def capture(window, name):
    directory = os.environ.get("SPX_UI_REPORT_DIR")
    if directory:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(directory / (name + ".png")))


with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(directory) / "local")}):
    store = Store(Path(directory) / "private")
    controller = Controller(store)
    window = Window(controller)
    window.show()
    QTest.qWait(100)
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert list(window.pages) == ["overview"], "Unused pages must be constructed lazily"
    assert window.next_button.isVisible()
    assert window.titlebar.controls["close"].isVisible()
    assert window.titlebar.caption.text().startswith("ENGE SPX") if window.compact else window.brand_label.width() >= window.brand_label.sizeHint().width()
    bounds, work = window.frameGeometry(), window.screen().availableGeometry()
    assert work.adjusted(-2, -2, 2, 2).contains(bounds), "Initial window leaves the monitor work area"
    capture(window, "overview")
    window.resize(1220, 860)
    QTest.qWait(60)
    assert not window.compact
    assert window.brand_label.width() >= window.brand_label.sizeHint().width()
    capture(window, "overview-wide")
    window.fit_to_screen()
    QTest.qWait(60)
    render_count = window.render_count
    QTest.qWait(1650)
    assert window.render_count == render_count, "Idle state must not repeatedly repaint the interface"
    assert not controller.delivery.isActive(), "Worker-delivery timer must sleep when idle"
    print("Native layout, complete branding, lazy pages and idle rendering passed", flush=True)
    for name in NAMES:
        window.show_page(name)
        QTest.qWait(30)
        assert window.pages[name].isVisible()
        if name in ("connection", "workspace"):
            capture(window, name)
    window.c.terminal_kind.set("pebrel")
    assert not window.terminal_args.isEnabled()
    window.c.terminal_kind.set("custom")
    assert window.terminal_args.isEnabled()
    controller.timezone.set("Etc/UTC")
    controller.refresh()
    assert not controller.view["matching"]
    controller.timezone.set(store.settings()["timezone"])
    nodes, unused = parse_nodes("socks5://demo:demo@127.0.0.1:1080#Landing")
    store.write("nodes.json", nodes)
    controller.refresh_nodes()
    assert controller.selected.get() == nodes[0]["id"]
    assert window.node_boxes[0][0].currentData() == nodes[0]["id"]
    assert not window.confirm_button.isEnabled()

    entered, release = threading.Event(), threading.Event()
    def fake_prepare(engine, settings, progress, cancel, **options):
        progress({"stage": "docker_wait", "message": "Isolated readiness check"})
        entered.set()
        assert release.wait(5)
        progress({"stage": "configure", "message": "Configure a landing"})
        return {"phase": "needs_configuration", "runtime": True, "docker": {"docker": "29.0.0", "architecture": "x86_64"}}
    store.write("nodes.json", [])
    controller.refresh_nodes()
    with patch("enge_spx.ui.controller.prepare_workspace", side_effect=fake_prepare), patch.object(window, "proxy_dialog") as dialog:
        controller.prepare()
        assert entered.wait(2)
        QTest.qWait(80)
        assert not window.next_button.isEnabled()
        assert window.startup_cancel.isEnabled()
        release.set()
        settle(controller)
        assert controller.docker_ready and controller.runtime_ok
        assert window.current_page == "connection"
        dialog.assert_called_once()
    def wait_for_cancel(engine, settings, progress, cancel, **options):
        assert cancel.wait(5)
        raise DownloadPaused("Preparation cancelled; data preserved")
    with patch("enge_spx.ui.controller.prepare_workspace", side_effect=wait_for_cancel):
        controller.prepare()
        controller.pause()
        settle(controller)
    assert not controller.startup_active
    print("Node binding, asynchronous preparation and cancellation passed", flush=True)

    original = store.home
    target = Path(directory) / "moved data"
    controller.data_target.set(str(target))
    previous_ask = controller.ask
    controller.ask = lambda *args: True
    with patch("enge_spx.ui.controller.prepare_workspace", return_value={"phase": "needs_runtime", "runtime": False, "docker": {"docker": "29.0.0", "architecture": "x86_64"}}):
        controller.migrate_data()
        settle(controller)
    controller.ask = previous_ask
    assert controller.store.home == target.resolve()
    assert Store(original).instance == controller.store.instance
    assert controller.data_location.get() == str(target.resolve())
    print("Application-data migration and installation identity passed", flush=True)

    window.minimize()
    QTest.qWait(50)
    assert window.isMinimized()
    window.reveal()
    QTest.qWait(50)
    assert window.isVisible() and not window.isMinimized()
    window.titlebar.toggle_maximize()
    QTest.qWait(80)
    assert window.isMaximized()
    assert window.screen().availableGeometry().adjusted(-2, -2, 2, 2).contains(window.frameGeometry()), "Maximized window overlaps the taskbar"
    window.titlebar.toggle_maximize()
    QTest.qWait(50)
    assert not window.isMaximized()
    print("Native minimize, restore and work-area maximization passed", flush=True)

    def answer(accept=False, enter=False):
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        buttons = dialog.findChildren(QPushButton)
        cancel = next(button for button in buttons if button.text() == "暂不继续")
        assert cancel.isDefault()
        if enter:
            QTest.keyClick(cancel, Qt.Key.Key_Return)
        elif accept:
            next(button for button in buttons if button.text() == "确认继续").click()
        else:
            dialog.reject()
    QTimer.singleShot(100, lambda: answer(True))
    assert confirm(window, "确认检查", "本次检查不访问 Docker。")
    QTimer.singleShot(100, answer)
    assert not confirm(window, "关闭检查", "关闭弹窗应取消。")
    QTimer.singleShot(100, lambda: answer(enter=True))
    assert not confirm(window, "键盘检查", "回车默认取消。")
    window.show_page("overview")
    if os.environ.get("SPX_UI_REPORT_DIR"):
        result = {"toolkit": "Qt", "custom_frame": True, "native_frame": os.name == "nt", "brand_visible": True, "lazy_pages": True, "idle_render_updates": 0, "maximize_restore": True, "minimize_restore": True, "modal_confirm_cancel": True, "default_confirmation_is_cancel": True, "all_pages_visible": True, "scale": window.devicePixelRatioF()}
        Path(os.environ["SPX_UI_REPORT_DIR"], "ui-checks.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    window.finish_close()
    app.processEvents()
    faulthandler.cancel_dump_traceback_later()
    print("Qt GUI smoke check passed", flush=True)
