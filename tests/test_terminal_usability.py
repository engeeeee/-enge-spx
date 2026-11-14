"""Native terminal interaction and VT capability regression, with synthetic data."""
import os
from pathlib import Path
import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QContextMenuEvent, QInputMethodEvent, QTextCharFormat, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QMenu

from enge_spx.clipboard import Snapshot
from enge_spx.clipboard_transfer import Attachment, InputAdapter, Transfer, text_frame
from enge_spx.smart_terminal import ImageAcknowledgement, OrderedInput, TerminalScreen, TerminalStream, TerminalWindow
from enge_spx.terminal_render import BACKGROUND, FOREGROUND


class AdapterCompatibilityTests(unittest.TestCase):
    def test_new_enter_after_failure_is_not_blocked_when_clock_values_are_identical(self):
        started, release, cancelled, delivered = (threading.Event() for _ in range(4))
        messages, written = [], []
        transfer, pty = Mock(tool="codex"), Mock()
        def fail(snapshot):
            started.set()
            release.wait(3)
            raise OSError("synthetic copy failure")
        def report(text):
            messages.append(text)
            if sum("已取消" in message for message in messages) == 2:
                cancelled.set()
        def write(data):
            written.append(data)
            if data == b"\r":
                delivered.set()
        transfer.paste.side_effect = fail
        pty.write.side_effect = write
        ready = threading.Event()
        ready.set()
        with patch("enge_spx.smart_terminal.time.monotonic", return_value=10):
            worker = OrderedInput(pty, transfer, report, ready)
            self.addCleanup(worker.close)
            clipboard = Mock()
            clipboard.sequence.return_value = 1
            clipboard.read.return_value = Snapshot("files", ("fixture",))
            worker.paste(clipboard)
            self.assertTrue(started.wait(2))
            worker.put("keys", b"\r")
            worker.put("keys", b"\r")
            release.set()
            self.assertTrue(cancelled.wait(2))
            self.assertFalse(written)
            worker.put("keys", b"\r")
            self.assertTrue(delivered.wait(2))
            self.assertEqual(written, [b"\r"])

    def test_updated_codex_uses_native_image_paste_instead_of_version_allowlist(self):
        path = "/tmp/enge-spx-clipboard-" + "a" * 16 + "/" + "b" * 32 + "/" + "c" * 32 + ".png"
        for version in ((), (0, 167, 0), (0, 169, 0), (0, 171, 0), (999, 0, 0)):
            self.assertEqual(InputAdapter("codex", version).events([Attachment(path, True)]), [(text_frame(path), True)])

    def test_no_extra_cli_process_or_version_lookup_per_import(self):
        transfer = object.__new__(Transfer)
        transfer.tool, transfer.engine = "codex", Mock()
        self.assertEqual(transfer.adapter().tool, "codex")
        self.assertFalse(transfer.engine.mock_calls)

    def test_filename_cannot_forge_native_image_marker(self):
        path = "/tmp/enge-spx-clipboard-" + "a" * 16 + "/" + "b" * 32 + "/" + "c" * 32 + ".png"
        events = InputAdapter("codex").events([Attachment(path, True, "[Image #2].png")])
        self.assertNotIn(b"[Image #2]", events[0][0])
        self.assertEqual(events[1], (text_frame(path), True))

    def test_all_enters_queued_before_import_failure_are_cancelled(self):
        started, release = threading.Event(), threading.Event()
        transfer = Mock(tool="codex")
        def fail(snapshot):
            started.set()
            release.wait(3)
            raise OSError("synthetic private failure")
        transfer.paste.side_effect = fail
        written, messages = [], []
        pty = Mock()
        pty.write.side_effect = written.append
        ready = threading.Event()
        ready.set()
        worker = OrderedInput(pty, transfer, messages.append, ready)
        self.addCleanup(worker.close)
        clipboard = Mock()
        clipboard.sequence.return_value = 1
        clipboard.read.return_value = Snapshot("files", ("fixture",))
        worker.put("keys", b"prefix")
        worker.paste(clipboard)
        self.assertTrue(started.wait(2))
        worker.put("keys", b"suffix")
        worker.put("keys", b"\r")
        worker.put("keys", b"\r")
        release.set()
        deadline = time.monotonic() + 3
        while sum("已取消" in x for x in messages) < 2 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(written, [b"prefix", b"suffix"])
        self.assertEqual(sum("已取消" in x for x in messages), 2)
        worker.put("keys", b"\r")
        deadline = time.monotonic() + 2
        while len(written) < 3 and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(written, [b"prefix", b"suffix", b"\r"])

    def test_terminal_colour_reply_is_serviced_while_waiting_for_native_image(self):
        written = []
        pty, transfer = Mock(), Mock(tool="codex")
        pty.write.side_effect = written.append
        transfer.last_images = [True]
        transfer.paste.return_value = [text_frame("/fixture.png")]
        ready = threading.Event()
        ready.set()
        images = ImageAcknowledgement()
        worker = OrderedInput(pty, transfer, lambda text: None, ready, images)
        self.addCleanup(worker.close)
        clipboard = Mock()
        clipboard.sequence.return_value = 1
        clipboard.read.return_value = Snapshot("files", ("fixture.png",))
        worker.paste(clipboard)
        deadline = time.monotonic() + 2
        while not written and time.monotonic() < deadline:
            time.sleep(.01)
        worker.put("keys", b"suffix")
        response = b"\x1b]11;rgb:1c1c/1a1a/1818\x1b\\"
        worker.respond(response)
        deadline = time.monotonic() + 2
        while response not in written and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(written, [text_frame("/fixture.png"), response])
        images.observe("[Image #1]")
        deadline = time.monotonic() + 2
        while b"suffix" not in written and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(written[-1], b"suffix")


class ColourProtocolTests(unittest.TestCase):
    def setUp(self):
        self.responses = []
        self.screen = TerminalScreen(80, 8, self.responses.append)
        self.stream = TerminalStream(self.screen)

    def test_ansi_256_truecolour_and_independent_faint_style(self):
        self.stream.feed("\x1b[31mR\x1b[0;38;5;196mX\x1b[38:2::12:34:56mT\x1b[2mD\x1b[22mN")
        line = self.screen.buffer[0]
        self.assertEqual(line[0].fg, "red")
        self.assertEqual(line[1].fg, "ff0000")
        self.assertEqual(line[2].fg, "0c2238")
        self.assertFalse(line[2].faint)
        self.assertTrue(line[3].faint)
        self.assertFalse(line[4].faint)

    def test_rgb_component_two_is_not_a_dim_instruction(self):
        self.stream.feed("\x1b[38;2;2;12;22mRGB")
        self.assertEqual(self.screen.buffer[0][0].fg, "020c16")
        self.assertFalse(self.screen.buffer[0][0].faint)

    def test_bold_italic_underline_strike_and_reset(self):
        self.stream.feed("\x1b[1;2;3;4:3;9mA\x1b[0mB")
        a, b = self.screen.buffer[0][0], self.screen.buffer[0][1]
        self.assertTrue(a.bold and a.faint and a.italics and a.underscore and a.strikethrough)
        self.assertFalse(b.bold or b.faint or b.italics or b.underscore or b.strikethrough)

    def test_colour_queries_across_chunk_boundaries_and_osc52_never_touches_clipboard(self):
        for char in "\x1b]10;?\x1b\\\x1b]11;?\x07\x1b]4;2;?\x07\x1b]52;c;cHJpdmF0ZQ==\x07safe":
            self.stream.feed(char)
        self.assertEqual(len(self.responses), 3)
        self.assertIn(TerminalStream._rgb(FOREGROUND).encode(), self.responses[0])
        self.assertIn(TerminalStream._rgb(BACKGROUND).encode(), self.responses[1])
        self.assertEqual("".join(self.screen.buffer[0][x].data for x in range(4)), "safe")

    def test_unterminated_osc_is_bounded_and_recovers_at_terminator(self):
        self.stream.feed("\x1b]52;" + "x" * 10000)
        self.assertLessEqual(len(self.stream.pending), 4096)
        self.stream.feed("ignored\x1b")
        self.stream.feed("\\after")
        self.assertEqual("".join(self.screen.buffer[0][x].data for x in range(5)), "after")


class TerminalUsabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.output, self.written = queue.Queue(), []
        self.pty, self.clipboard = Mock(), Mock()
        self.pty.read.side_effect = self.output.get
        self.pty.write.side_effect = self.written.append
        self.pty.close.side_effect = lambda: self.output.put(b"")
        self.window = TerminalWindow(self.pty, "codex", Path("synthetic-project"), clipboard=self.clipboard)
        self.window.show()
        self.view = self.window.view
        self.view.setFocus()
        self.output.put(b"\x1b[?2004h")
        self.pump(lambda: self.view.ready.is_set())

    def tearDown(self):
        self.window.close()
        self.view.reader.join(1)
        self.app.processEvents()

    def pump(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate())

    def point(self, column, row=0):
        return QPoint(round(self.view.PAD_X + (column + .3) * self.view.cell_width),
                      round(self.view.PAD_Y + (row + .4) * self.view.cell_height))

    def preedit(self, text, attributes=()):
        QApplication.sendEvent(self.view, QInputMethodEvent(text, list(attributes)))
        self.app.processEvents()

    def test_ime_preedit_masks_placeholder_and_cancel_restores_original(self):
        self.view.stream.feed("\x1b[1;1HAsk Codex to do anything\x1b[1;1H")
        self.view.blink = False
        original = self.view.grab().toImage()
        self.preedit("wo xiang 输入")
        composing = self.view.grab().toImage()
        self.assertNotEqual(original, composing)
        self.assertEqual(self.view.screen.buffer[0][0].data, "A")
        self.assertFalse(self.written, "Uncommitted IME text must stay out of the CLI")
        # Painting over a placeholder must equal painting over empty cells.
        self.view.stream.feed("\x1b[2K")
        rectangle = self.view.rect().adjusted(self.view.PAD_X, 0, 0, 0)
        self.assertEqual(composing.copy(rectangle), self.view.grab().toImage().copy(rectangle))
        self.view.stream.feed("Ask Codex to do anything\x1b[1;1H")
        self.preedit("")
        self.assertEqual(original, self.view.grab().toImage())
        self.assertFalse(self.written)

    def test_ime_commit_is_sent_once_without_enter_or_duplicate_preedit(self):
        self.preedit("zhong wen")
        self.assertFalse(self.written)
        event = QInputMethodEvent()
        event.setCommitString("中文🙂")
        QApplication.sendEvent(self.view, event)
        self.pump(lambda: bool(self.written))
        self.assertEqual(self.written, ["中文🙂".encode()])
        self.assertEqual(self.view.preedit, "")

    def test_ime_baseline_format_and_utf16_candidate_position(self):
        self.view.stream.feed("\x1b[3;5H")
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#654638"))
        attributes = [QInputMethodEvent.Attribute(QInputMethodEvent.AttributeType.Cursor, 3, 1, None),
                      QInputMethodEvent.Attribute(QInputMethodEvent.AttributeType.TextFormat, 0, 3, fmt)]
        self.preedit("🙂A中文", attributes)
        layout, masks, caret = self.view.composition_layout()
        line = layout.lineAt(0)
        self.assertAlmostEqual(line.y() + line.ascent(), self.view.PAD_Y + 2 * self.view.cell_height + self.view.metrics.ascent())
        self.assertAlmostEqual(caret.x(), line.cursorToX(3)[0])
        self.assertEqual(caret.toAlignedRect(), self.view.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle))
        self.assertEqual(len(layout.formats()), 2)
        self.assertEqual(masks[0].right(), self.view.PAD_X + self.view.screen.columns * self.view.cell_width)
        self.assertFalse(self.written)

    def test_ime_wrap_stays_inside_terminal_and_keeps_native_buffer(self):
        column = self.view.screen.columns - 3
        self.view.stream.feed(f"\x1b[2;{column + 1}H")
        self.preedit("long preedit 中文 composition")
        layout, masks, caret = self.view.composition_layout()
        self.assertGreater(len(masks), 1)
        self.assertEqual(masks[1].left(), self.view.PAD_X)
        self.assertGreaterEqual(caret.top(), masks[1].top())
        self.assertLessEqual(caret.right(), self.view.PAD_X + self.view.screen.columns * self.view.cell_width + 2)
        self.assertEqual(self.view.screen.cursor.x, column)
        self.assertFalse(self.written)

    def test_shift_right_click_keeps_menu_without_reading_clipboard(self):
        QTest.mouseClick(self.view, Qt.MouseButton.RightButton, Qt.KeyboardModifier.ShiftModifier, self.point(2))
        self.app.processEvents()
        self.clipboard.read.assert_not_called()
        self.assertFalse(self.written)
        menu = self.view.create_context_menu()
        self.assertFalse(next(a for a in menu.actions() if a.objectName() == "TerminalCopy").isEnabled())
        self.assertTrue(next(a for a in menu.actions() if a.objectName() == "TerminalPaste").isEnabled())
        menu.deleteLater()

    def test_right_click_pastes_once_without_submitting_or_opening_menu(self):
        self.clipboard.sequence.return_value = 3
        self.clipboard.read.return_value = Snapshot("text", "中文\nclipboard")
        QTest.mouseClick(self.view, Qt.MouseButton.RightButton, pos=self.point(2))
        self.pump(lambda: bool(self.written))
        self.assertEqual(self.written, [text_frame("中文\nclipboard")])
        self.clipboard.read.assert_called_once()
        point = self.point(2)
        QApplication.sendEvent(self.view, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, self.view.mapToGlobal(point)))
        self.app.processEvents()
        self.assertFalse(any(m.isVisible() for m in self.view.findChildren(QMenu)))

    def test_native_single_click_is_deferred_and_delivered_without_arrow_keys(self):
        self.output.put(b"\x1b[?1000h\x1b[?1006h")
        self.pump(lambda: self.view.screen.mouse)
        QTest.mousePress(self.view, Qt.MouseButton.LeftButton, pos=self.point(5, 2))
        time.sleep(.02)
        self.assertFalse(self.written)
        QTest.mouseRelease(self.view, Qt.MouseButton.LeftButton, pos=self.point(5, 2))
        self.pump(lambda: bool(self.written))
        self.assertEqual(self.written, [b"\x1b[<0;6;3M\x1b[<0;6;3m"])

    def test_drag_copies_even_when_cli_requests_mouse_without_moving_its_cursor(self):
        self.output.put("copy 中文\x1b[?1000h\x1b[?1006h".encode())
        self.pump(lambda: self.view.screen.mouse)
        QTest.mousePress(self.view, Qt.MouseButton.LeftButton, pos=self.point(0))
        QTest.mouseMove(self.view, self.point(8))
        QTest.mouseRelease(self.view, Qt.MouseButton.LeftButton, pos=self.point(8))
        self.assertEqual(QGuiApplication.clipboard().text(), "copy 中文")
        self.assertFalse(self.written)

    def test_single_click_does_not_overwrite_clipboard(self):
        QGuiApplication.clipboard().setText("synthetic previous clipboard")
        QTest.mouseClick(self.view, Qt.MouseButton.LeftButton, pos=self.point(3))
        self.assertEqual(QGuiApplication.clipboard().text(), "synthetic previous clipboard")

    def test_autocopy_can_be_disabled_without_losing_manual_copy(self):
        self.output.put(b"manual")
        self.pump(lambda: self.view.screen.buffer[0][0].data == "m")
        QGuiApplication.clipboard().setText("keep")
        self.view.copy_on_select = False
        QTest.mousePress(self.view, Qt.MouseButton.LeftButton, pos=self.point(0))
        QTest.mouseMove(self.view, self.point(5))
        QTest.mouseRelease(self.view, Qt.MouseButton.LeftButton, pos=self.point(5))
        self.assertEqual(QGuiApplication.clipboard().text(), "keep")
        self.view.copy()
        self.assertEqual(QGuiApplication.clipboard().text(), "manual")

    def test_drag_select_unicode_and_copy_via_context_menu(self):
        self.output.put("hello 世界!\r\n".encode())
        self.pump(lambda: self.view.screen.buffer[0][0].data == "h")
        QTest.mousePress(self.view, Qt.MouseButton.LeftButton, pos=self.point(0))
        QTest.mouseMove(self.view, self.point(9))
        QTest.mouseRelease(self.view, Qt.MouseButton.LeftButton, pos=self.point(9))
        self.assertTrue(self.view.has_selection)
        self.assertEqual(QGuiApplication.clipboard().text(), "hello 世界")
        menu = self.view.create_context_menu()
        copy = next(a for a in menu.actions() if a.objectName() == "TerminalCopy")
        self.assertTrue(copy.isEnabled())
        copy.trigger()
        self.assertEqual(QGuiApplication.clipboard().text(), "hello 世界")
        self.clipboard.read.assert_not_called()
        menu.deleteLater()

    def test_select_all_includes_history_and_keeps_snapshot_during_output(self):
        self.output.put("".join("fixture-%03d\r\n" % i for i in range(100)).encode())
        self.pump(lambda: len(self.view.screen.history.top) > 30)
        self.view.select_all()
        self.output.put(b"new-output-must-not-replace-selection\r\n")
        self.pump(lambda: self.view.output.empty())
        self.view.copy()
        copied = QGuiApplication.clipboard().text()
        self.assertIn("fixture-000", copied)
        self.assertIn("fixture-099", copied)
        self.assertNotIn("new-output", copied)

    def test_click_without_drag_keeps_ctrl_c_interrupt(self):
        QTest.mouseClick(self.view, Qt.MouseButton.LeftButton, pos=self.point(1))
        self.assertFalse(self.view.has_selection)
        QTest.keyClick(self.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.pump(lambda: bool(self.written))
        self.assertEqual(self.written, [b"\x03"])

    def test_keyboard_zoom_resizes_same_pty_without_sending_keys(self):
        QTest.keyClick(self.view, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.view.font.pointSize(), 12)
        QTest.keyClick(self.view, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.view.font.pointSize(), 11)
        self.assertFalse(self.written)
        self.pty.resize.assert_called()

    def test_actual_context_menu_opens_even_when_cli_requests_mouse(self):
        self.output.put(b"selectable\x1b[?1000h\x1b[?1006h")
        self.pump(lambda: self.view.screen.mouse)
        self.view.select_all()
        point = self.point(3)
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, self.view.mapToGlobal(point))
        QApplication.sendEvent(self.view, event)
        self.app.processEvents()
        menu = self.view.findChild(QMenu, "TerminalMenu")
        self.assertIsNotNone(menu)
        self.assertTrue(menu.isVisible())
        copy = next(a for a in menu.actions() if a.objectName() == "TerminalCopy")
        copy.trigger()
        self.assertIn("selectable", QGuiApplication.clipboard().text())
        self.clipboard.read.assert_not_called()
        menu.close()

    def test_shift_drag_selects_with_mouse_reporting_and_preserves_plain_ctrl_a(self):
        self.output.put(b"hello world\x1b[?1000h\x1b[?1006h")
        self.pump(lambda: self.view.screen.mouse)
        QTest.mousePress(self.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, self.point(0))
        QTest.mouseMove(self.view, self.point(4))
        QTest.mouseRelease(self.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, self.point(4))
        self.view.copy()
        self.assertEqual(QGuiApplication.clipboard().text(), "hello")
        self.assertFalse(self.written)
        self.view.clear_selection()
        QTest.keyClick(self.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.pump(lambda: bool(self.written))
        self.assertEqual(self.written, [b"\x01"])

    def test_double_click_copies_unicode_word(self):
        self.output.put("日志文件.txt next".encode())
        self.pump(lambda: self.view.screen.buffer[0][0].data == "日")
        QTest.mouseDClick(self.view, Qt.MouseButton.LeftButton, pos=self.point(2))
        self.view.copy()
        self.assertEqual(QGuiApplication.clipboard().text(), "日志文件.txt")

    def test_custom_frame_and_removed_copy_button(self):
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(set(self.window.titlebar.controls), {"minimize", "maximize", "close"})
        self.assertEqual(len(self.window.resize_edges), 8)
        self.assertFalse(any("复制" in w.text() for w in self.window.findChildren(QPushButton)))

    def test_copy_and_display_options_remain_available_after_disconnect(self):
        self.window.connection_ended()
        self.view.select_all()
        menu = self.view.create_context_menu()
        self.assertFalse(next(a for a in menu.actions() if a.objectName() == "TerminalPaste").isEnabled())
        self.view.zoom(1)
        menu.deleteLater()
