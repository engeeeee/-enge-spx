"""Capture the real unconfigured UI in a temporary data directory.

No accounts, nodes, exit results or running-workspace status are fabricated.
No startup/check/tool action is clicked. Windows CI supplies native screenshots;
other platforms can use this command for a separately labeled local preview.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PySide6
from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from enge_spx import __version__
from enge_spx.state import Store
from enge_spx.ui import style
from enge_spx.ui.controller import Controller
from enge_spx.ui.window import Window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    style.apply(app)
    captures = []
    with tempfile.TemporaryDirectory(prefix="spx-readme-") as directory:
        controller = Controller(Store(Path(directory) / "data"))
        window = Window(controller)
        window.show()
        try:
            for page in ("overview", "workspace", "connection", "resources"):
                window.show_page(page)
                if page == "resources":
                    window.select_resource_view("budget")
                window.resize(1280, 1000)
                window.pages[page].verticalScrollBar().setValue(0)
                QTest.qWait(150)
                assert not window.compact, "Gallery requires the full navigation"
                assert window.brand_label.width() >= window.brand_label.sizeHint().width(), "Product name is cropped"
                assert window.brand_label.height() >= window.brand_label.sizeHint().height(), "Product name is cropped"
                if page == "workspace":
                    viewport = window.pages[page].viewport()
                    for title in ("Claude Code", "Codex"):
                        control = next(button for button in window.pages[page].findChildren(QPushButton) if button.text().startswith(title))
                        bounds = QRect(control.mapTo(viewport, QPoint()), control.size())
                        assert viewport.rect().contains(bounds), f"{title} launch control is cropped"
                target = args.output / (page + ".png")
                picture = window.grab()
                assert picture.save(str(target))
                captures.append({"file": target.name, "page": page, "width": picture.width(), "height": picture.height(), "logical_width": window.width(), "logical_height": window.height(), "device_pixel_ratio": window.devicePixelRatioF(), "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        finally:
            window.finish_close()
    report = {"version": __version__, "source_commit": os.environ.get("GITHUB_SHA"), "platform": platform.system(), "python": platform.python_version(), "qt": PySide6.__version__, "captured_utc": datetime.now(timezone.utc).isoformat(), "state": "unconfigured temporary data; no accounts, proxies or Docker workspace started", "captures": captures}
    (args.output / "capture.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
