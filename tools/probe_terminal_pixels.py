"""Synthetic pixel-reference and resize-cost probe; never reads clipboard/accounts."""
import argparse
import json
import math
import os
from pathlib import Path
import queue
import statistics
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'src')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--loops', type=int, default=24)
args = parser.parse_args()
if not 8 <= args.loops <= 80:
    parser.error('loops must be 8..80')
sys.path.insert(0, str(args.source))
if os.name != 'nt':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF, QRectF, qVersion
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from enge_spx.smart_terminal import TerminalView


class FixturePTY:
    def __init__(self): self.queue = queue.Queue()
    def read(self): return self.queue.get()
    def write(self, value): pass
    def resize(self, *args): pass
    def close(self): self.queue.put(b'')


def summary(values):
    return {'median_ms': round(statistics.median(values), 3), 'p95_ms': round(sorted(values)[int(len(values)*.95)-1], 3)}


def scene():
    lines = ['const value = await client.run(); 0123456789', 'Unicode 中文  e\u0301  🙂',
             '\x1b[31mRed / GREEN\x1b[0m', '\x1b[1;2mBold faint HMW iii\x1b[0m',
             '\x1b[3mItalic italic ffi\x1b[0m', 'Stable text at different window proportions']
    return '\x1b[?2026h\x1b[?25l\x1b[2J' + ''.join(f'\x1b[{y+1};1H{text}' for y, text in enumerate(lines)) + '\x1b[?2026l'


def reference(view):
    """Single-pass Qt glyph drawing at integer physical origins, no row bitmap."""
    dpr = view.devicePixelRatioF()
    image = QImage(math.ceil(view.width()*dpr), math.ceil(view.height()*dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.setDotsPerMeterX(round(view.logicalDpiX() / .0254))
    image.setDotsPerMeterY(round(view.logicalDpiY() / .0254))
    image.fill(view.background)
    painter = QPainter(image)
    blank = view.screen.default_char
    x = round(view.PAD_X*dpr) / dpr
    for y in range(min(6, view.screen.lines)):
        row = view.screen.buffer[y]
        cells = tuple(row.get(column, blank) for column in range(view.screen.columns))
        fills, glyphs = view.row_painter.layout(cells, None)
        top = round((view.PAD_Y+y*view.cell_height)*dpr) / dpr
        painter.save()
        painter.translate(x, top)
        for left, width, color in fills:
            painter.fillRect(QRectF(left, 0, width, view.cell_height), color)
        for left, text, (fg, bg, font) in glyphs:
            painter.setFont(font)
            painter.setPen(fg)
            painter.drawStaticText(QPointF(left, 0), text)
        painter.restore()
    painter.end()
    return image


def difference(actual, expected):
    if actual == expected:
        return {'channels_over_tolerance': 0, 'max_channel_delta': 0}
    left, right = bytes(actual.constBits()), bytes(expected.constBits())
    count = maximum = 0
    for a, b in zip(left, right):
        delta = abs(a-b)
        count += delta > 2  # allow premultiplied-alpha rounding, not glyph shifts
        maximum = max(maximum, delta)
    return {'channels_over_tolerance': count, 'max_channel_delta': maximum}


app = QApplication([])
host = QWidget()
host.resize(800, 600)
pty = FixturePTY()
view = TerminalView(pty)
view.setParent(host)
host.show()
view.show()
view.blink_timer.stop()
view.blink = False
cases = []
args.output.parent.mkdir(parents=True, exist_ok=True)
try:
    for index, (width, height) in enumerate(((1001, 633), (1179, 761), (1597, 997), (1919, 1079), (701, 953), (1807, 431))):
        view.resize(width, height)
        app.processEvents()
        view.stream.feed(scene())
        view._compose_surface()
        dpr = view.devicePixelRatioF()
        crop_width = math.ceil(min(width, 520)*dpr)
        crop_height = math.ceil((view.PAD_Y*2+6*view.cell_height)*dpr)
        actual = view.surface.copy(0, 0, crop_width, crop_height)
        expected = reference(view).copy(0, 0, crop_width, crop_height)
        cases.append({'viewport': [width, height], 'grid': [view.screen.columns, view.screen.lines],
                      'physical_line_height': view.cell_height*dpr, **difference(actual, expected)})
        if index == 0:
            assert actual.save(str(args.output.with_name(args.output.stem+'-actual.png')))
            assert expected.save(str(args.output.with_name(args.output.stem+'-reference.png')))
    durations, allocations, rebuilds = [], 0, 0
    for index in range(args.loops):
        previous_image, painter = view.surface, view.row_painter
        builds = painter.raster_builds
        started = time.perf_counter()
        view.resize(1001+index*3, 730)
        app.processEvents()
        view.stream.feed(scene())
        view._compose_surface()
        durations.append((time.perf_counter()-started)*1000)
        allocations += view.surface is not previous_image
        rebuilds += view.row_painter.raster_builds-builds if view.row_painter is painter else view.row_painter.raster_builds
    snapshots = []
    for _ in range(args.loops):
        started = time.perf_counter()
        view._capture_frame()
        snapshots.append((time.perf_counter()-started)*1000)
    report = {'schema': 1, 'scope': 'Synthetic resize, synchronized VT and single-pass Qt pixel reference; not physical monitor FPS or subjective font quality',
              'system': sys.platform, 'qt': qVersion(), 'dpr': view.devicePixelRatioF(), 'font': view.font.toString(),
              'logical_dpi': [view.logicalDpiX(), view.logicalDpiY()], 'cases': cases,
              'pixel_reference_passed': all(case['channels_over_tolerance'] == 0 for case in cases),
              'resize_feed_present': summary(durations), 'completed_frame_snapshot': summary(snapshots),
              'resize_steps': args.loops, 'surface_allocations_during_resize': allocations,
              'row_raster_builds_during_resize': rebuilds, 'row_raster_bytes': view.row_painter.raster_bytes}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
finally:
    view.stop()
    view.close()
    host.close()
    view.reader.join(2)
