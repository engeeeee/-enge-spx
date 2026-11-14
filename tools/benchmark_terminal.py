"""Synthetic terminal rendering benchmark. Never reads accounts or clipboard."""
import argparse
import json
import os
from pathlib import Path
import platform
import queue
import statistics
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "src")
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--frames", type=int, default=60)
args = parser.parse_args()
if not 5 <= args.frames <= 300:
    parser.error("frames must be 5..300")
sys.path.insert(0, str(args.source))
if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import qVersion
from enge_spx.smart_terminal import TerminalView


class FixturePTY:
    def __init__(self):
        self.output = queue.Queue()
    def read(self):
        return self.output.get()
    def resize(self, *args):
        pass
    def write(self, *args):
        pass
    def close(self):
        self.output.put(b"")


def measure(operation):
    values = []
    for index in range(args.frames):
        started = time.perf_counter()
        operation(index)
        values.append((time.perf_counter() - started) * 1000)
    return {"median_ms": round(statistics.median(values), 3),
            "p95_ms": round(sorted(values)[int(len(values) * .95) - 1], 3)}


app = QApplication([])
pty = FixturePTY()
view = TerminalView(pty)
view.resize(1440, 860)
view.show()
app.processEvents()
view.blink_timer.stop()
view.blink = False
scene = "".join(f"\x1b[{y + 1};1H\x1b[38;2;180;190;200m" +
                ('const value = build("terminal", 42); // 中文日志 ' * 8)[:view.screen.columns - 20]
                for y in range(view.screen.lines))
view.stream.feed(scene)
image = QImage(view.size(), QImage.Format.Format_ARGB32_Premultiplied)
view.render(image)
try:
    stable = measure(lambda _: view.render(image))
    def typing(index):
        view.stream.feed(f"\x1b[20;5H{index:04d}")
        view.render(image)
    edited = measure(typing)
    def full(index):
        view.stream.feed(scene.replace("42", f"{index % 100:02d}"))
        view.render(image)
    redraw = measure(full)
    report = {"scope": "Synthetic Qt widget; render cost, not physical monitor FPS or real AI latency",
              "system": platform.system(), "architecture": platform.machine(), "python": platform.python_version(),
              "qt": qVersion(), "font": view.font.family(), "dpr": view.devicePixelRatioF(),
              "size": [view.width(), view.height()], "grid": [view.screen.columns, view.screen.lines],
              "frames_per_case": args.frames, "stable_redraw": stable, "single_row_edit_and_full_paint": edited,
              "full_parse_and_paint": redraw}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
finally:
    view.stop()
    view.reader.join(2)
