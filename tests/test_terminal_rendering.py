import os
import queue
import time
import unittest

if os.name != 'nt':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from enge_spx.smart_terminal import TerminalView
from enge_spx.terminal_preferences import DEFAULTS


class FixturePTY:
    def __init__(self):
        self.queue = queue.Queue()
        self.writes = []
    def read(self):
        return self.queue.get()
    def write(self, data):
        self.writes.append(data)
    def resize(self, *args):
        pass
    def close(self):
        self.queue.put(b'')


class TerminalRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pty = FixturePTY()
        self.view = TerminalView(self.pty)
        self.view.resize(1000, 620)
        self.view.show()
        self.app.processEvents()
        self.view.blink_timer.stop()
        self.view.blink = False

    def tearDown(self):
        self.view.stop()
        self.view.close()
        self.view.reader.join(2)
        self.app.processEvents()

    def image(self):
        # Native scrollbar hover/focus animation is outside the terminal grid.
        # Compare rendered content, rather than timing-dependent child chrome.
        return self.view.grab().toImage().copy(0, 0, self.view.width() - 14, self.view.height())

    def pump(self, predicate, seconds=5):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    def test_layout_cache_reuses_static_rows_and_refreshes_text_style_selection_and_font(self):
        self.view.stream.feed('English 中文 e\u0301 🙂\x1b[31m RED\x1b[0m')
        before = self.image()
        builds = self.view.row_painter.layout_builds
        self.assertEqual(self.image(), before)
        self.assertEqual(self.view.row_painter.layout_builds, builds)
        self.view.stream.feed('\x1b[1;1H\x1b[32mUpdated\x1b[0m')
        changed = self.image()
        self.assertNotEqual(changed, before)
        self.view.select_all()
        self.assertNotEqual(self.image(), changed)
        self.view.clear_selection()
        self.assertEqual(self.image(), changed)
        self.view.zoom(1)
        self.assertNotEqual(self.image(), changed)

    def test_cache_is_bounded_under_many_different_terminal_rows(self):
        for index in range(180):
            self.view.stream.feed(f'\x1b[1;1H{index:05d} 中文 cache boundary')
            self.image()
        self.assertLessEqual(self.view.row_painter.cells, self.view.row_painter.MAX_CELLS)
        self.assertLessEqual(len(self.view.row_painter.rows), self.view.row_painter.MAX_ROWS)

    def test_translucent_background_replaces_old_pixels_while_text_stays_opaque(self):
        self.view.apply_display({**DEFAULTS, 'tint': 'purple', 'opacity': 60}, glass=True)
        self.view.stream.feed('Readability')
        first = self.image()
        second = self.image()
        self.assertEqual(first, second)
        self.assertFalse(self.view.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent))
        self.assertEqual(self.view.background.alpha(), 153)
        self.view.apply_display(DEFAULTS, glass=False)
        self.assertEqual(self.view.background.alpha(), 255)
        self.assertTrue(self.view.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent))

    def test_burst_yields_to_keyboard_and_eof_preserves_the_last_screen(self):
        ended, ticks = [], []
        self.view.ended.connect(lambda: ended.append(True))
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        payload = b'\x1b[1;1H' + b'burst output row\r\n' * 12000 + b'SPX_LAST_OUTPUT'
        self.pty.queue.put(payload)
        self.pty.queue.put(b'')
        QTimer.singleShot(2, lambda: self.view.sender.put('keys', b'input-still-responsive'))
        self.pump(lambda: bool(ended), seconds=12)
        timer.stop()
        self.assertIn(b'input-still-responsive', self.pty.writes)
        self.assertGreater(len(ticks), 3)
        self.assertIn('SPX_LAST_OUTPUT', '\n'.join(self.view.screen.display))

    def test_synchronized_erase_and_partial_redraw_keep_last_complete_pixels(self):
        self.view.stream.feed('Old completed frame 中文')
        before = self.image()
        self.view.stream.feed('\x1b[?2026h\x1b[2J\x1b[H')
        self.assertEqual(self.image(), before)
        self.view.stream.feed('New top half')
        self.assertEqual(self.image(), before)
        self.view.stream.feed('\x1b[5;1HNew bottom half\x1b[?2026l')
        after = self.image()
        self.assertNotEqual(after, before)
        self.assertIn('New bottom half', '\n'.join(self.view.screen.display))
        self.assertEqual(self.image(), after)

    def test_synchronized_query_split_sequences_and_broken_child_deadline(self):
        replies = []
        self.view.screen.respond = replies.append
        for char in '\x1b[?2026$p':
            self.view.stream.feed(char)
        self.assertEqual(replies, [b'\x1b[?2026;2$y'])
        self.view.stream.feed('Initial')
        before = self.image()
        for char in '\x1b[?2026h\x1b[?2026$p\x1b[2J':
            self.view.stream.feed(char)
        self.assertEqual(replies[-1], b'\x1b[?2026;1$y')
        self.assertEqual(self.image(), before)
        self.view.stream.synchronized_at = time.monotonic() - .16
        self.assertNotEqual(self.image(), before)
        self.assertIsNone(self.view.stream.synchronized_at)

    def test_static_expose_and_cursor_do_not_rebuild_row_rasters(self):
        self.view.stream.feed('Static 中文 🙂 \x1b[31mRED')
        self.image()
        built = self.view.row_painter.raster_builds
        self.image()
        self.view.stream.feed('\x1b[2;2H')
        self.image()
        self.assertEqual(self.view.row_painter.raster_builds, built)
        self.assertLessEqual(self.view.row_painter.raster_bytes, self.view.row_painter.MAX_RASTER_BYTES)

    def test_busy_pipe_presents_completed_frame_before_following_partial_frame(self):
        self.view.stream.feed('First')
        first = self.image()
        self.view.stream.feed('\x1b[?2026h\x1b[2J\x1b[HSecond\x1b[?2026l\x1b[?2026h\x1b[2J\x1b[HPartial third')
        second = self.image()
        self.assertNotEqual(first, second)
        self.assertEqual(self.image(), second)
        self.assertEqual(self.view.presented_generation, self.view.completed_generation)
        self.view.stream.feed('\x1b[?2026l')
        self.assertNotEqual(self.image(), second)

    def test_resize_during_synchronized_frame_does_not_use_old_grid_snapshot(self):
        self.view.stream.feed('\x1b[?2026hOld grid\x1b[?2026l')
        self.view.resize(800, 480)
        self.app.processEvents()
        self.image()
        self.view.stream.feed('\x1b[?2026h\x1b[2J\x1b[HNew grid\x1b[?2026l')
        self.image()
        self.assertEqual(len(self.view.surface_rows), self.view.screen.lines)

    def test_width_resize_reuses_ink_rasters_instead_of_viewport_padding(self):
        self.view.stream.feed('Stable resize text 中文')
        self.image()
        painter, builds = self.view.row_painter, self.view.row_painter.raster_builds
        for width in (1007, 1031, 1087, 1133, 1000):
            self.view.resize(width, 620)
            self.image()
        self.assertIs(self.view.row_painter, painter)
        self.assertEqual(painter.raster_builds, builds)

    def test_background_opacity_preserves_opaque_text_and_row_cache(self):
        self.view.stream.feed('Opacity keeps text sharp\x1b[7m reversed\x1b[0m')
        original = self.image()
        painter, builds = self.view.row_painter, self.view.row_painter.raster_builds
        layouts = painter.layout_builds
        for opacity in (65, 100):
            self.view.apply_display({**DEFAULTS, 'opacity': opacity}, glass=True)
            self.image()
            self.assertIs(self.view.row_painter, painter)
            self.assertEqual(painter.layout_builds, layouts)
        builds = painter.raster_builds
        for opacity in (65, 100, 65, 100):
            self.view.apply_display({**DEFAULTS, 'opacity': opacity}, glass=True)
            self.image()
            self.assertEqual(painter.raster_builds, builds)
        reverse = next(char for char in self.view.screen.buffer[0].values() if char.reverse)
        self.assertEqual(painter.style(reverse, False)[0].alpha(), 255)
        self.view.apply_display(DEFAULTS, glass=False)
        self.assertEqual(self.image(), original)

    def test_resize_while_frame_held_rerasterizes_committed_text_at_new_size(self):
        self.view.stream.feed('Committed before resize')
        self.image()
        self.view.stream.feed('\x1b[?2026h\x1b[2J\x1b[HPartial hidden frame')
        self.view.resize(1093, 687)
        self.image()
        self.assertGreaterEqual(self.view.surface.width(), round(self.view.width() * self.view.devicePixelRatioF()))
        text = ''.join(char.data for record in self.view.surface_rows if record for char in record[0])
        self.assertIn('Committed before resize', text)
        self.assertNotIn('Partial hidden frame', text)
        self.view.stream.feed('\x1b[?2026l')
        self.image()
        text = ''.join(char.data for record in self.view.surface_rows if record for char in record[0])
        self.assertIn('Partial hidden frame', text)

    def test_surface_reserve_reuses_small_resizes_and_shrinks_when_needed(self):
        self.view.stream.feed('Surface capacity')
        self.image()
        allocations = self.view.surface_allocations
        for width in range(1001, 1042, 2):
            self.view.resize(width, 620)
            self.image()
        self.assertLessEqual(self.view.surface_allocations - allocations, 2)
        self.view.resize(600, 400)
        self.image()
        pixels = self.view.width() * self.view.height() * self.view.devicePixelRatioF() ** 2
        self.assertLessEqual(self.view.surface.width() * self.view.surface.height(), pixels * 2)
        self.assertAlmostEqual(self.view.cell_height * self.view.devicePixelRatioF(), round(self.view.cell_height * self.view.devicePixelRatioF()))
