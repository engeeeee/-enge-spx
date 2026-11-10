"""Check visible branding and the primary action at the current Qt DPI scale."""
from pathlib import Path
import json
import os
import tempfile

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractSpinBox
from enge_spx.state import Store
from enge_spx.ui import style
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window

app = QApplication([])
style.apply(app)
with tempfile.TemporaryDirectory() as directory:
    controller = Controller(Store(Path(directory)))
    window = Window(controller)
    window.show()
    QTest.qWait(150)
    if window.compact:
        assert window.titlebar.caption.text().startswith("ENGE SPX")
        assert window.titlebar.caption.width() >= window.titlebar.caption.sizeHint().width(), "Compact product name is cropped"
    else:
        assert window.brand_label.width() >= window.brand_label.sizeHint().width(), "Sidebar product name is cropped"
    viewport = window.pages["overview"].viewport()
    action = QRect(window.next_button.mapTo(viewport, QPoint()), window.next_button.size())
    assert viewport.rect().contains(action), f"Primary action is clipped: {action} / {viewport.rect()}"
    assert window.screen().availableGeometry().adjusted(-2, -2, 2, 2).contains(window.frameGeometry())
    report = {"scale": window.devicePixelRatioF(), "width": window.width(), "height": window.height(), "compact": window.compact, "brand_visible": True, "primary_action_visible": True}
    target = os.environ.get("SPX_UI_REPORT_DIR")
    if target:
        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        name = "dpi-" + os.environ.get("QT_SCALE_FACTOR", "native")
        window.grab().save(str(path / (name + ".png")))
        (path / (name + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    window.show_page("resources")
    window.select_resource_view("budget")
    QTest.qWait(80)
    page = window.pages["resources"]
    viewport = page.viewport()
    action = QRect(window.resource_save_button.mapTo(viewport, QPoint()), window.resource_save_button.size())
    assert viewport.rect().contains(action), f"Resource save action is clipped: {action} / {viewport.rect()}"
    for widget in page.findChildren(QAbstractSpinBox):
        page.ensureWidgetVisible(widget)
        QTest.qWait(10)
        rect = QRect(widget.mapTo(viewport, QPoint()), widget.size())
        assert rect.left() >= 0 and rect.right() <= viewport.width(), f"Resource input is horizontally clipped: {rect} / {viewport.rect()}"
    page.verticalScrollBar().setValue(0)
    report["resource_budget_controls_visible"] = True
    if target:
        window.grab().save(str(path / (name + "-resources.png")))
        (path / (name + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    window.show_page("workspace")
    QTest.qWait(80)
    page = window.pages["workspace"]
    for widget in (window.workspace_profile_box, window.workspace_apply_button):
        page.ensureWidgetVisible(widget)
        QTest.qWait(20)
        rect = QRect(widget.mapTo(page.viewport(), QPoint()), widget.size())
        assert rect.left() >= 0 and rect.right() <= page.viewport().width(), f"Workspace identity control is clipped: {rect}"
    page.verticalScrollBar().setValue(0)
    report["workspace_identity_controls_visible"] = True
    if target:
        window.grab().save(str(path / (name + "-workspaces.png")))
        (path / (name + ".json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    window.finish_close()
