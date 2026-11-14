"""Reproducible full-size scrolling and split-frame proof, using synthetic VT only."""
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
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'src')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--width', type=int, default=1920)
parser.add_argument('--height', type=int, default=1080)
parser.add_argument('--frames', type=int, default=30)
args = parser.parse_args()
if not 5 <= args.frames <= 120 or not 640 <= args.width <= 3840 or not 400 <= args.height <= 2160:
    parser.error('invalid bounded viewport/frame count')
sys.path.insert(0, str(args.source))
if os.name != 'nt':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import qVersion
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from enge_spx.smart_terminal import TerminalView


class FixturePTY:
    def __init__(self):
        self.queue = queue.Queue()
    def read(self): return self.queue.get()
    def write(self, value): pass
    def resize(self, *args): pass
    def close(self): self.queue.put(b'')


app = QApplication([])
pty = FixturePTY()
view = TerminalView(pty)
view.show()
view.resize(args.width, args.height)  # after show: no automatic desktop-size clamp
app.processEvents()
view.blink_timer.stop()
view.blink = False
view.scrollbar.hide()
canvas = QImage(view.size(), QImage.Format.Format_ARGB32_Premultiplied)
canvas.setDevicePixelRatio(view.devicePixelRatioF())


def scene(index):
    lines = []
    for row in range(view.screen.lines):
        label = f'LOG {row+index:05d} '
        text = (label + 'const value = await run(); // 中文日志 ' * 12)[:max(1, view.screen.columns - 8)]
        lines.append(f'\x1b[{row+1};1H\x1b[38;2;180;190;200m{text}')
    return ''.join(lines)


def render():
    view.render(canvas)
    return canvas


try:
    prefix = '\x1b[?25l\x1b[H\x1b[2J'
    view.stream.feed(prefix + scene(0))
    render()
    values = []
    for index in range(args.frames):
        text = prefix + scene(index + 1)
        started = time.perf_counter()
        view.stream.feed(text)
        render()
        values.append((time.perf_counter() - started) * 1000)
    # An expose/paint between packets must show the last complete screen, even
    # when the child erased its live VT buffer and only redrew half the rows.
    view.stream.feed(prefix + scene(0))
    previous = render().copy()
    view.stream.feed(prefix + scene(1))
    expected = render().copy()
    view.stream.feed(prefix + scene(0))
    render()
    pieces = scene(1).split('\x1b[')
    split = max(1, len(pieces) // 2)
    view.stream.feed('\x1b[?2026h' + prefix)
    samples = [render().copy()]
    view.stream.feed('\x1b['.join(pieces[:split]))
    samples.append(render().copy())
    view.stream.feed('\x1b[' + '\x1b['.join(pieces[split:]))
    samples.append(render().copy())
    view.stream.feed('\x1b[?2026l')
    final = render().copy()
    bad = sum(sample != previous for sample in samples)
    assert final == expected, 'final completed frame does not match the complete reference'
    report = {'schema': 1, 'scope': 'Synthetic full-size VT scroll and controlled packet-boundary paints; not physical monitor FPS',
              'system': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version(),
              'qt': qVersion(), 'viewport': [view.width(), view.height()], 'grid': [view.screen.columns, view.screen.lines],
              'dpr': view.devicePixelRatioF(), 'frames': args.frames,
              'scroll_parse_and_present': {'median_ms': round(statistics.median(values), 3),
                                            'p95_ms': round(sorted(values)[int(len(values)*.95)-1], 3)},
              'split_frame_paints': len(samples), 'premature_or_torn_paints': bad, 'final_frame_exact': True,
              'row_raster_bytes': getattr(view.row_painter, 'raster_bytes', None) if hasattr(view, 'row_painter') else None,
              'surface_bytes': view.surface.sizeInBytes() if hasattr(view, 'surface') else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
finally:
    view.stop()
    view.close()
    view.reader.join(2)
