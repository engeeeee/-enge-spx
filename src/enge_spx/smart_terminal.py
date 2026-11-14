"""Native Qt terminal: local paste events -> the existing CLI's owned Linux PTY.

This is a terminal display, not a replacement chat composer or CLI protocol.
The CLI owns its input buffer, editing, history, attachments and submission.
"""
from __future__ import annotations

from concurrent.futures import Future
from collections import Counter, defaultdict
from copy import deepcopy
import codecs
import os
import queue
import re
import threading
import time

import pyte
from PySide6.QtCore import Qt, QTimer, Signal, QEvent, QRectF, QSize, QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QKeySequence, QPainter, QContextMenuEvent, QInputMethodEvent, QTextLayout, QTextOption, QTextCharFormat
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollBar, QFrame, QMenu, QToolButton, QSizePolicy

from .clipboard import WindowsClipboard
from .clipboard_transfer import Transfer, text_frame
from .state import SPXError
from .terminal_render import BACKGROUND, FOREGROUND, PALETTE, TerminalChar, TerminalStream, sgr_attributes


class TerminalScreen(pyte.HistoryScreen):
    def __init__(self, columns, lines, respond=lambda data: None):
        self.respond = respond
        self.primary = None
        super().__init__(columns, lines, history=2000)

    @property
    def default_char(self):
        return TerminalChar(*super().default_char, False)

    def reset(self):
        super().reset()
        self.cursor.attrs = TerminalChar(**self.cursor.attrs._asdict())

    def select_graphic_rendition(self, *attrs):
        if not attrs:
            super().select_graphic_rendition()
            return
        self.cursor.attrs = TerminalChar(**self.cursor.attrs._asdict())
        forwarded, faint = sgr_attributes(attrs, self.cursor.attrs.faint)
        if forwarded:
            super().select_graphic_rendition(*forwarded)
        self.cursor.attrs = self.cursor.attrs._replace(faint=faint)

    @property
    def bracketed(self):
        return (2004 << 5) in self.mode

    @property
    def application_cursor(self):
        return (1 << 5) in self.mode

    @property
    def mouse(self):
        return any((m << 5) in self.mode for m in (1000, 1002, 1003)) and (1006 << 5) in self.mode

    def write_process_input(self, data):
        self.respond(data.encode("utf-8"))

    def set_mode(self, *modes, **kwargs):
        if kwargs.get("private") and any(m in (47, 1047, 1049) for m in modes) and self.primary is None:
            self.primary = deepcopy((self.buffer, self.cursor, self.history, self.margins))
            self.buffer.clear()
            self.cursor_position()
            self.dirty.update(range(self.lines))
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        super().reset_mode(*modes, **kwargs)
        if kwargs.get("private") and any(m in (47, 1047, 1049) for m in modes) and self.primary is not None:
            self.buffer, self.cursor, self.history, self.margins = self.primary
            self.primary = None
            self.dirty.update(range(self.lines))


def key_bytes(event, application_cursor=False):
    key, modifiers, text = event.key(), event.modifiers(), event.text()
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return b"\x1b[13;2u" if shift else b"\r"
    if key == Qt.Key.Key_Backspace and (ctrl or alt):
        return b"\x17" if ctrl else b"\x1b\x7f"
    if key == Qt.Key.Key_Delete and (ctrl or alt or shift):
        number = 1 + int(shift) + 2 * int(alt) + 4 * int(ctrl)
        return f"\x1b[3;{number}~".encode()
    special = {Qt.Key.Key_Backspace: b"\x7f", Qt.Key.Key_Escape: b"\x1b", Qt.Key.Key_Tab: b"\t",
               Qt.Key.Key_Backtab: b"\x1b[Z", Qt.Key.Key_Insert: b"\x1b[2~", Qt.Key.Key_Delete: b"\x1b[3~",
               Qt.Key.Key_PageUp: b"\x1b[5~", Qt.Key.Key_PageDown: b"\x1b[6~"}
    if key in special:
        return special[key]
    arrows = {Qt.Key.Key_Up: "A", Qt.Key.Key_Down: "B", Qt.Key.Key_Right: "C", Qt.Key.Key_Left: "D", Qt.Key.Key_Home: "H", Qt.Key.Key_End: "F"}
    if key in arrows:
        number = 1 + int(shift) + 2 * int(alt) + 4 * int(ctrl)
        prefix = ("\x1b[1;" + str(number)) if number != 1 else ("\x1bO" if application_cursor else "\x1b[")
        return (prefix + arrows[key]).encode()
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return [b"\x1bOP", b"\x1bOQ", b"\x1bOR", b"\x1bOS", b"\x1b[15~", b"\x1b[17~", b"\x1b[18~", b"\x1b[19~", b"\x1b[20~", b"\x1b[21~", b"\x1b[23~", b"\x1b[24~"][key - Qt.Key.Key_F1]
    if ctrl and Qt.Key.Key_A <= key <= Qt.Key.Key_Z and not alt:
        return bytes([key - Qt.Key.Key_A + 1])
    if ctrl and key in (Qt.Key.Key_Space, Qt.Key.Key_At):
        return b"\0"
    controls = {Qt.Key.Key_BracketLeft: 27, Qt.Key.Key_Backslash: 28, Qt.Key.Key_BracketRight: 29, Qt.Key.Key_AsciiCircum: 30, Qt.Key.Key_Underscore: 31}
    if ctrl and key in controls:
        return bytes([controls[key]])
    if text and not ctrl:
        return (b"\x1b" if alt else b"") + text.encode("utf-8")
    # Ctrl+Alt produced by AltGr is ordinary Unicode input.
    if text and ctrl and alt and text.isprintable():
        return text.encode("utf-8")
    return b""


class ImageAcknowledgement:
    """Observe native [Image #N] chips, never equate a copied path with success."""
    def __init__(self):
        self.condition = threading.Condition()
        self.counts = Counter()

    def observe(self, text):
        with self.condition:
            self.counts = Counter(re.findall(r"\[Image\s*#?(\d+)\]", text))
            self.condition.notify_all()

    def ticket(self):
        with self.condition:
            return self.counts.copy()

    def wait(self, ticket, cancelled, timeout=5, service=None):
        deadline = time.monotonic() + timeout
        while not cancelled.is_set():
            if service is not None:
                service()
            with self.condition:
                if any(count > ticket[number] for number, count in self.counts.items()):
                    return True
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.condition.wait(min(left, .025))
        return False


class OrderedInput:
    """One writer preserves typing/paste/Enter order even during a large copy."""
    def __init__(self, pty, transfer, report, ready, images=None):
        self.pty, self.transfer, self.report, self.ready = pty, transfer, report, ready
        self.queue = queue.Queue(maxsize=2048)
        self.replies = queue.Queue(maxsize=64)
        self.sequence_lock = threading.Lock()
        self.sequence = 0
        self.images = images
        self.closed = threading.Event()
        self.pastes = threading.BoundedSemaphore(8)
        self.thread = threading.Thread(target=self._run, name="spx-terminal-input", daemon=True)
        self.thread.start()

    def put(self, kind, value):
        if self.closed.is_set():
            return False
        try:
            self.enqueue(kind, value)
        except queue.Full:
            self.report("输入队列已满，请稍候；本次输入未发送。")
            return False
        return True

    def enqueue(self, kind, value):
        with self.sequence_lock:
            self.sequence += 1
            self.queue.put_nowait((kind, value, self.sequence))

    def failure_boundary(self):
        with self.sequence_lock:
            return self.sequence

    def respond(self, data):
        if self.closed.is_set():
            return
        try:
            self.replies.put_nowait(data)
        except queue.Full:
            return
        try:
            self.enqueue("reply", None)
        except queue.Full:
            pass

    def flush_replies(self):
        for _ in range(16):
            if self.closed.is_set():
                return
            try:
                reply = self.replies.get_nowait()
            except queue.Empty:
                return
            self.pty.write(reply)

    def _run(self):
        failed_sequence = 0
        while not self.closed.is_set():
            try:
                kind, value, sequence = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                self.flush_replies()
                if kind == "keys":
                    if sequence <= failed_sequence and value == b"\r":
                        self.report("上次粘贴失败，已取消这次回车。输入仍保留；检查后可再次回车。")
                        continue
                    self.pty.write(value)
                elif kind == "paste":
                    snapshot = value.result(timeout=2)
                    if snapshot.kind == "empty":
                        self.report("剪贴板为空或没有支持的内容。")
                        continue
                    if not self.ready.is_set():
                        raise SPXError("工具输入区尚未启用安全粘贴，请等待 CLI 就绪后重试。")
                    if snapshot.kind == "text":
                        self.pty.write(text_frame(snapshot.value))
                    else:
                        if self.transfer is None or self.transfer.tool not in ("claude", "codex"):
                            raise SPXError("当前终端只支持文字粘贴；请在 Claude Code / Codex 输入区粘贴附件。")
                        self.report("正在导入附件…可以继续输入，操作会按顺序完成。")
                        frames = self.transfer.paste(snapshot)
                        images = getattr(self.transfer, "last_images", None)
                        if not isinstance(images, list) or len(images) != len(frames):
                            images = [False] * len(frames)
                        for frame, image in zip(frames, images):
                            if self.closed.is_set():
                                break
                            if image and self.images is None:
                                raise SPXError("当前终端未启用原生图片确认，附件未插入。")
                            ticket = self.images.ticket() if image and self.images else None
                            self.pty.write(frame)
                            # Separate native paste events; no Enter, clearing,
                            # hotkey injection or new CLI process is involved.
                            if ticket is not None and not self.images.wait(ticket, self.closed, service=self.flush_replies):
                                raise SPXError("CLI 未确认原生图片附件。请检查输入区是否出现 [Image #N]；若只显示路径，请删除该路径并确认模型支持图片后重试。本次排队的回车将取消。")
                            time.sleep(.02)
                        self.report("附件已交给 CLI；请检查原生图片标记或文件引用，再自行发送。")
            except SPXError as error:
                failed_sequence = self.failure_boundary()
                self.report(str(error))
            except Exception:
                failed_sequence = self.failure_boundary()
                # Do not propagate raw clipboard/OS/CLI errors into logs/UI.
                self.report("粘贴或输入未完成。当前草稿保留；请检查文件权限、大小、CLI 版本和工作区连接后重试。")
            finally:
                if kind == "paste":
                    self.pastes.release()
                    snapshot = None
                value = None

    def paste(self, clipboard):
        if self.closed.is_set():
            self.report("终端连接已结束，请从 ENGE SPX 重新打开工具后粘贴。")
            return
        if not self.pastes.acquire(blocking=False):
            self.report("已有 8 次粘贴等待处理，请稍候。")
            return
        sequence, result = clipboard.sequence(), Future()
        if not self.put("paste", result):
            self.pastes.release()
            return
        def capture():
            if not result.set_running_or_notify_cancel():
                return
            try:
                if self.closed.is_set():
                    raise SPXError("终端已关闭。")
                snapshot = clipboard.read(sequence)
                if self.closed.is_set():
                    raise SPXError("终端已关闭。")
                result.set_result(snapshot)
            except BaseException as error:
                result.set_exception(error)
        threading.Thread(target=capture, name="spx-clipboard-snapshot", daemon=True).start()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        while True:
            try:
                kind, value, sequence = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "paste":
                value.cancel()
                self.pastes.release()
        if self.transfer is not None:
            self.transfer.close()
        # Closing the owned PTY may wait for output draining; never block Qt.
        threading.Thread(target=self.pty.close, name="spx-terminal-close", daemon=True).start()


class TerminalView(QWidget):
    status = Signal(str)
    wake = Signal()
    ended = Signal()
    selection_changed = Signal(bool)
    font_changed = Signal(int)
    readiness_changed = Signal(bool)
    PAD_X, PAD_Y = 16, 12

    def __init__(self, pty, transfer=None, clipboard=None):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setMinimumSize(480, 260)
        self.pty, self.clipboard = pty, clipboard
        self.ready = threading.Event()
        self.images = ImageAcknowledgement()
        self.sender = OrderedInput(pty, transfer, self.status.emit, self.ready, self.images)
        self.screen = TerminalScreen(110, 32, self.sender.respond)
        self.stream = TerminalStream(self.screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.output = queue.Queue(maxsize=64)
        self.pending = threading.Event()
        self.stopping = threading.Event()
        self.wake.connect(self._drain)
        self.font = QFont()
        self.font.setFamilies(["Cascadia Mono", "Cascadia Code", "Consolas"] if os.name == "nt" else ["DejaVu Sans Mono", "Liberation Mono"])
        self.font.setPointSize(11)
        self.font.setStyleHint(QFont.StyleHint.Monospace)
        self.font.setFixedPitch(True)
        self.font.setKerning(False)
        self.setFont(self.font)
        self.metrics = QFontMetricsF(self.font)
        self.cell_width = self.metrics.horizontalAdvance("M")
        self.cell_height = self.metrics.height() + 2
        self.selection = None
        self.selection_lines = None
        self.explicit_selection = False
        self.copy_on_select = True
        self.right_click_paste = True
        self.left_press = None
        self.left_drag = False
        self.native_drag = False
        self.quick_paste_click = False
        self.selecting = False
        self.preedit = ""
        self.preedit_formats = []
        self.preedit_cursor = 0
        self.preedit_cursor_visible = True
        self.offset = 0
        self.colors = {}
        self.fonts = {}
        self.scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self.scrollbar.valueChanged.connect(self._scroll)
        self.blink = True
        self.blink_timer = QTimer(self)
        self.blink_timer.setInterval(600)
        self.blink_timer.timeout.connect(self._blink)
        self.blink_timer.start()
        self.reader = threading.Thread(target=self._read, name="spx-terminal-output", daemon=True)
        self.reader.start()

    def _read(self):
        try:
            # Keep draining after the window stops. ClosePseudoConsole can
            # otherwise deadlock while flushing a full output pipe.
            while True:
                data = self.pty.read()
                if not data:
                    break
                if self.stopping.is_set():
                    continue
                while not self.stopping.is_set():
                    try:
                        self.output.put(data, timeout=.2)
                        if not self.pending.is_set():
                            self.pending.set()
                            self.wake.emit()
                        break
                    except queue.Full:
                        continue
        finally:
            if not self.stopping.is_set():
                self.ended.emit()

    def _drain(self):
        start = time.monotonic()
        changed = False
        while time.monotonic() - start < .008:
            try:
                data = self.output.get_nowait()
            except queue.Empty:
                break
            self.stream.feed(self.decoder.decode(data))
            changed = True
        was_ready = self.ready.is_set()
        if self.screen.bracketed:
            self.ready.set()
        else:
            self.ready.clear()
        if was_ready != self.ready.is_set():
            self.readiness_changed.emit(self.ready.is_set())
        if changed:
            self.images.observe("".join("".join(self.screen.buffer[y][x].data for x in range(self.screen.columns)) for y in range(self.screen.lines)))
        self.scrollbar.setRange(0, max(0, len(self.selection_lines) - self.screen.lines) if self.selection_lines is not None else len(self.screen.history.top))
        if self.offset == 0:
            self.scrollbar.setValue(self.scrollbar.maximum())
        if changed:
            self.update_input_method()
            self.update()
        if not self.output.empty():
            QTimer.singleShot(0, self._drain)
        else:
            self.pending.clear()
            # Close the producer/consumer race without one signal per chunk.
            if not self.output.empty() and not self.pending.is_set():
                self.pending.set()
                self.wake.emit()

    def _blink(self):
        if self.hasFocus() and self.isVisible():
            self.blink = not self.blink
            cursor = self.screen.cursor
            self.update(QRectF(self.PAD_X + cursor.x * self.cell_width, self.PAD_Y + cursor.y * self.cell_height, self.cell_width, self.cell_height).toAlignedRect())

    def _scroll(self, value):
        self.offset = self.scrollbar.maximum() - value
        self.update()

    def rows(self):
        if self.selection_lines is not None:
            start = self.selection_start()
            return self.selection_lines[start:start + self.screen.lines]
        current = [self.screen.buffer[y] for y in range(self.screen.lines)]
        if not self.offset:
            return current
        lines = [*self.screen.history.top, *current]
        end = len(lines) - self.offset
        return lines[max(0, end - self.screen.lines):end]

    def selection_start(self):
        return max(0, len(self.selection_lines) - self.offset - self.screen.lines) if self.selection_lines is not None else 0

    @property
    def has_selection(self):
        return self.selection is not None and (self.explicit_selection or self.selection[0] != self.selection[1])

    def clear_selection(self):
        self.selection = self.selection_lines = None
        self.explicit_selection = False
        self.selecting = False
        self.left_press = None
        self.left_drag = False
        self.selection_changed.emit(False)
        self.scrollbar.setRange(0, len(self.screen.history.top))
        self.update()

    def snapshot_selection(self):
        if self.selection_lines is None:
            blank = self.screen.default_char
            self.selection_lines = [defaultdict(lambda: blank, line) for line in
                                    [*self.screen.history.top, *(self.screen.buffer[y] for y in range(self.screen.lines))]]

    def select_all(self):
        self.clear_selection()
        self.snapshot_selection()
        self.selection = ((0, 0), (len(self.selection_lines) - 1, self.screen.columns - 1))
        self.explicit_selection = True
        self.selection_changed.emit(True)
        self.update()

    def zoom(self, amount=0, reset=False):
        size = 11 if reset else min(24, max(8, self.font.pointSize() + amount))
        if size == self.font.pointSize():
            return
        self.font.setPointSize(size)
        self.setFont(self.font)
        self.metrics = QFontMetricsF(self.font)
        self.cell_width, self.cell_height = self.metrics.horizontalAdvance("M"), self.metrics.height() + 2
        self.fonts.clear()
        self._resize_grid()
        self.font_changed.emit(size)
        self.update()

    def _color(self, value, foreground=True):
        key = (value, foreground)
        if key in self.colors:
            return self.colors[key]
        named = {"default": FOREGROUND if foreground else BACKGROUND, **PALETTE}
        result = QColor(named.get(value, "#" + value if re.fullmatch("[a-fA-F0-9]{6}", value) else named["default"]))
        if len(self.colors) >= 512:
            self.colors.clear()
        self.colors[key] = result
        return result

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BACKGROUND))
        p.setFont(self.font)
        selected = sorted(self.selection) if self.has_selection else None
        first = self.selection_start()
        clip = event.rect()
        for y, line in enumerate(self.rows()):
            if self.PAD_Y + (y + 1) * self.cell_height < clip.top() or self.PAD_Y + y * self.cell_height > clip.bottom():
                continue
            glyphs = []
            for x in range(self.screen.columns):
                if self.PAD_X + (x + 1) * self.cell_width < clip.left() or self.PAD_X + x * self.cell_width > clip.right():
                    continue
                char = line[x]
                rectangle = QRectF(self.PAD_X + x * self.cell_width, self.PAD_Y + y * self.cell_height, self.cell_width, self.cell_height)
                fg, bg = self._color(char.fg), self._color(char.bg, False)
                if char.reverse:
                    fg, bg = bg, fg
                if getattr(char, "faint", False):
                    key = ("faint", fg.rgb(), bg.rgb())
                    if key not in self.colors:
                        if len(self.colors) >= 512:
                            self.colors.clear()
                        self.colors[key] = QColor(*(round(a * .58 + b * .42) for a, b in zip(fg.getRgb()[:3], bg.getRgb()[:3])))
                    fg = self.colors[key]
                if selected and selected[0] <= (y + first, x) <= selected[1]:
                    bg = QColor("#654638")
                    fg = QColor(FOREGROUND)
                if bg != QColor(BACKGROUND):
                    p.fillRect(rectangle, bg)
                if char.data and char.data != " ":
                    glyphs.append((rectangle, char, fg))
            # Paint wide glyphs after ALL cell backgrounds, so a CJK character
            # cannot have its second half erased by the continuation cell.
            for rectangle, char, fg in glyphs:
                    key = (char.bold, char.italics, char.underscore, char.strikethrough)
                    font = self.fonts.get(key)
                    if font is None:
                        font = QFont(self.font)
                        font.setBold(char.bold)
                        font.setItalic(char.italics)
                        font.setUnderline(char.underscore)
                        font.setStrikeOut(char.strikethrough)
                        self.fonts[key] = font
                    p.setFont(font)
                    p.setPen(fg)
                    p.drawText(rectangle.left(), rectangle.top() + self.metrics.ascent(), char.data)
        cursor = self.screen.cursor
        if not self.preedit and self.blink and self.hasFocus() and self.selection_lines is None and self.offset == 0 and not cursor.hidden:
            p.fillRect(QRectF(self.PAD_X + cursor.x * self.cell_width, self.PAD_Y + cursor.y * self.cell_height, 2, self.cell_height), QColor("#d89979"))
        if self.preedit and self.offset == 0 and self.selection_lines is None:
            layout, masks, caret = self.composition_layout()
            p.save()
            p.setClipRect(QRectF(self.PAD_X, self.PAD_Y, self.screen.columns * self.cell_width, self.screen.lines * self.cell_height))
            # Preedit belongs to the input method, not the CLI buffer. Hide
            # placeholder/suffix cells temporarily; cancellation restores them.
            for rectangle in masks:
                p.fillRect(rectangle, QColor(BACKGROUND))
            p.setFont(self.font)
            p.setPen(QColor(FOREGROUND))
            layout.draw(p, QPointF())
            if self.hasFocus() and self.preedit_cursor_visible:
                p.fillRect(caret, QColor("#d89979"))
            p.restore()

    def resizeEvent(self, event):
        self._resize_grid()

    def _resize_grid(self):
        self.scrollbar.setGeometry(self.width() - 12, 4, 10, self.height() - 8)
        columns = max(20, int((self.width() - 12 - 2 * self.PAD_X) / self.cell_width))
        rows = max(5, int((self.height() - 2 * self.PAD_Y) / self.cell_height))
        self.screen.resize(lines=rows, columns=columns)
        if not self.stopping.is_set():
            self.pty.resize(columns, rows)
        self.clear_selection()
        self.update_input_method()

    def paste(self):
        if self.stopping.is_set():
            self.status.emit("终端连接已结束，请从 ENGE SPX 重新打开工具后粘贴。")
            return
        if self.clipboard is None:
            self.status.emit("系统剪贴板桥接仅在 Windows 中启用。")
            return
        self.clear_selection()
        self.offset = 0
        self.sender.paste(self.clipboard)

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        if event.key() == Qt.Key.Key_Menu or (event.key() == Qt.Key.Key_F10 and modifiers & Qt.KeyboardModifier.ShiftModifier):
            rect = self.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
            self.open_context_menu(self.mapToGlobal(rect.bottomLeft()))
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier and modifiers & Qt.KeyboardModifier.ShiftModifier and event.key() == Qt.Key.Key_A:
            self.select_all()
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_0):
            self.zoom(-1 if event.key() == Qt.Key.Key_Minus else 1, event.key() == Qt.Key.Key_0)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.has_selection:
            self.clear_selection()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste) or (event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.paste()
            event.accept()
            return
        ctrl_c = event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if (self.has_selection and (event.matches(QKeySequence.StandardKey.Copy) or ctrl_c)) or (ctrl_c and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.copy()
            event.accept()
            return
        self.clear_selection()
        self.offset = 0
        data = key_bytes(event, self.screen.application_cursor)
        if data:
            self.sender.put("keys", data)
        self.update()
        event.accept()

    def event(self, event):
        # QWidget otherwise moves focus before Tab/Backtab reaches the CLI.
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(event)
            return True
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def inputMethodEvent(self, event):
        if event.commitString():
            self.sender.put("keys", event.commitString().encode("utf-8"))
        self.preedit = event.preeditString()
        self.preedit_cursor = len(self.preedit.encode("utf-16-le")) // 2
        self.preedit_cursor_visible = True
        self.preedit_formats = []
        for attribute in event.attributes():
            if attribute.type == QInputMethodEvent.AttributeType.Cursor:
                self.preedit_cursor = attribute.start
                self.preedit_cursor_visible = bool(attribute.length)
            elif attribute.type == QInputMethodEvent.AttributeType.TextFormat:
                item = QTextLayout.FormatRange()
                item.start, item.length = attribute.start, attribute.length
                item.format = QTextCharFormat(attribute.value)
                self.preedit_formats.append(item)
        self.update_input_method()
        self.update()
        event.accept()

    def composition_layout(self):
        """Native IME preedit, aligned to the terminal baseline, without echo."""
        layout = QTextLayout(self.preedit, self.font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAnywhere)
        layout.setTextOption(option)
        base = QTextLayout.FormatRange()
        base.start, base.length = 0, len(self.preedit.encode("utf-16-le")) // 2
        base.format.setForeground(QColor(FOREGROUND))
        base.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DashUnderline)
        layout.setFormats([base, *self.preedit_formats])
        cursor = self.screen.cursor
        row, column = cursor.y, min(cursor.x, self.screen.columns - 1)
        masks, caret = [], None
        position = max(0, min(base.length, self.preedit_cursor))
        layout.beginLayout()
        while row < self.screen.lines:
            line = layout.createLine()
            if not line.isValid():
                break
            x, y = self.PAD_X + column * self.cell_width, self.PAD_Y + row * self.cell_height
            width = (self.screen.columns - column) * self.cell_width
            line.setLineWidth(width)
            line.setPosition(QPointF(x, y + self.metrics.ascent() - line.ascent()))
            masks.append(QRectF(x, y, width, self.cell_height))
            if line.textStart() <= position <= line.textStart() + line.textLength():
                caret = QRectF(line.cursorToX(position)[0], y, 2, self.cell_height)
            row, column = row + 1, 0
        layout.endLayout()
        if caret is None:
            caret = masks[-1] if masks else QRectF(self.PAD_X, self.PAD_Y, 2, self.cell_height)
            caret = QRectF(caret.right() - 2, caret.top(), 2, self.cell_height)
        return layout, masks, caret

    def update_input_method(self):
        if self.hasFocus():
            QGuiApplication.inputMethod().update(Qt.InputMethodQuery.ImCursorRectangle | Qt.InputMethodQuery.ImFont)

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            if self.preedit:
                return self.composition_layout()[2].toAlignedRect()
            cursor = self.screen.cursor
            return QRectF(self.PAD_X + cursor.x * self.cell_width, self.PAD_Y + cursor.y * self.cell_height, self.cell_width, self.cell_height).toRect()
        if query == Qt.InputMethodQuery.ImFont:
            return self.font
        return super().inputMethodQuery(query)

    def cell(self, event):
        return (max(0, min(self.screen.lines - 1, int((event.position().y() - self.PAD_Y) / self.cell_height))),
                max(0, min(self.screen.columns - 1, int((event.position().x() - self.PAD_X) / self.cell_width))))

    def mouse_packet(self, event, button, release=False):
        y, x = self.cell(event)
        modifiers = event.modifiers()
        button += (4 if modifiers & Qt.KeyboardModifier.ShiftModifier else 0)
        button += (8 if modifiers & Qt.KeyboardModifier.AltModifier else 0)
        button += (16 if modifiers & Qt.KeyboardModifier.ControlModifier else 0)
        return f"\x1b[<{button};{x+1};{y+1}{'m' if release else 'M'}".encode()

    def mousePressEvent(self, event):
        self.setFocus()
        y, x = self.cell(event)
        if event.button() == Qt.MouseButton.RightButton:
            self.quick_paste_click = (self.right_click_paste and self.ready.is_set() and
                                      self.clipboard is not None and not self.stopping.is_set() and
                                      not event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            native = self.screen.mouse and self.offset == 0 and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            self.clear_selection()
            if native and event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.native_drag = True
                self.sender.put("keys", self.mouse_packet(event, 0))
                return
            self.snapshot_selection()
            self.selection = ((y + self.selection_start(), x), (y + self.selection_start(), x))
            self.left_press = (event.position(), self.mouse_packet(event, 0), native)
            self.left_drag = False
            self.selecting = True
            self.update()
        elif event.button() == Qt.MouseButton.MiddleButton and self.screen.mouse and self.offset == 0:
            self.sender.put("keys", self.mouse_packet(event, 1))

    def mouseMoveEvent(self, event):
        if self.selecting:
            if self.left_press is not None and not self.left_drag:
                delta = event.position() - self.left_press[0]
                if abs(delta.x()) + abs(delta.y()) < min(QApplication.startDragDistance(), max(3, self.cell_width / 2)):
                    return
                self.left_drag = True
                self.explicit_selection = True
            y, x = self.cell(event)
            self.selection = (self.selection[0], (y + self.selection_start(), x))
            self.selection_changed.emit(self.has_selection)
            self.update()
        elif self.screen.mouse and self.offset == 0 and self.selection_lines is None and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if event.buttons() & Qt.MouseButton.RightButton or (event.buttons() & Qt.MouseButton.LeftButton and not self.native_drag):
                return
            motion = (1003 << 5) in self.screen.mode or ((1002 << 5) in self.screen.mode and event.buttons())
            if motion:
                button = 0 if event.buttons() & Qt.MouseButton.LeftButton else 1 if event.buttons() & Qt.MouseButton.MiddleButton else 3
                self.sender.put("keys", self.mouse_packet(event, 32 + button))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.quick_paste_click = False
            elif self.quick_paste_click:
                self.paste()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self.native_drag:
                self.native_drag = False
                self.sender.put("keys", self.mouse_packet(event, 0, True))
                return
            click = self.left_press
            if click is not None and not self.left_drag:
                delta = event.position() - click[0]
                if abs(delta.x()) + abs(delta.y()) >= min(QApplication.startDragDistance(), max(3, self.cell_width / 2)):
                    y, x = self.cell(event)
                    self.left_drag = self.explicit_selection = True
                    self.selection = (self.selection[0], (y + self.selection_start(), x))
            if self.has_selection:
                if self.copy_on_select:
                    self.copy()
            elif click is not None and click[2] and self.screen.mouse and self.offset == 0 and not self.left_drag:
                # A genuine native click, never synthetic arrows or edits to
                # the CLI buffer. Delay until release to distinguish dragging.
                self.sender.put("keys", click[1] + self.mouse_packet(event, 0, True))
            self.left_press = None
            self.left_drag = False
        elif event.button() == Qt.MouseButton.MiddleButton and self.screen.mouse and self.offset == 0:
            self.sender.put("keys", self.mouse_packet(event, 1, True))
        self.selecting = False
        if not self.has_selection:
            self.clear_selection()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or event.modifiers() & Qt.KeyboardModifier.AltModifier:
            return self.mousePressEvent(event)
        self.clear_selection()
        self.snapshot_selection()
        y, x = self.cell(event)
        y += self.selection_start()
        line = self.selection_lines[y]
        while x > 0 and not line[x].data:
            x -= 1
        def word(column):
            value = line[column].data
            return not value or all(c.isalnum() or c in "_./:~-@%+\\" for c in value)
        left = right = x
        if word(x):
            while left > 0 and word(left - 1):
                left -= 1
            while right + 1 < self.screen.columns and word(right + 1):
                right += 1
        self.selection = ((y, left), (y, right))
        self.explicit_selection = True
        self.selecting = False
        self.selection_changed.emit(True)
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1 if event.angleDelta().y() > 0 else -1)
        elif self.screen.mouse and self.offset == 0 and self.selection_lines is None and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.sender.put("keys", self.mouse_packet(event, 64 if event.angleDelta().y() > 0 else 65))
        else:
            self.scrollbar.setValue(self.scrollbar.value() - event.angleDelta().y() // 40)

    def copy(self):
        if not self.has_selection:
            return
        (y1, x1), (y2, x2) = sorted(self.selection)
        lines = self.selection_lines if self.selection_lines is not None else self.rows()
        text = []
        for y in range(y1, y2 + 1):
            left, right = (x1 if y == y1 else 0), (x2 + 1 if y == y2 else self.screen.columns)
            text.append("".join(lines[y][x].data for x in range(left, right)).rstrip())
        QGuiApplication.clipboard().setText("\n".join(text).rstrip("\n"))
        self.status.emit("已复制所选终端文字。")

    def create_context_menu(self):
        menu = QMenu(self)
        menu.setObjectName("TerminalMenu")
        copy = menu.addAction("复制\tCtrl+Shift+C", self.copy)
        copy.setObjectName("TerminalCopy")
        copy.setEnabled(self.has_selection)
        paste = menu.addAction("粘贴文字、截图或文件\tCtrl+V", self.paste)
        paste.setObjectName("TerminalPaste")
        paste.setEnabled(not self.stopping.is_set() and self.clipboard is not None and self.ready.is_set())
        menu.addAction("全选输出\tCtrl+Shift+A", self.select_all)
        clear = menu.addAction("取消选择\tEsc", self.clear_selection)
        clear.setEnabled(self.has_selection)
        menu.addSeparator()
        selection = menu.addAction("拖选后自动复制")
        selection.setCheckable(True)
        selection.setChecked(self.copy_on_select)
        selection.toggled.connect(lambda enabled: setattr(self, "copy_on_select", enabled))
        quick = menu.addAction("右键直接粘贴 · Shift+右键打开菜单")
        quick.setCheckable(True)
        quick.setChecked(self.right_click_paste)
        quick.toggled.connect(lambda enabled: setattr(self, "right_click_paste", enabled))
        menu.addSeparator()
        menu.addAction("放大字号\tCtrl++", lambda: self.zoom(1))
        menu.addAction("缩小字号\tCtrl+-", lambda: self.zoom(-1))
        menu.addAction("重置字号\tCtrl+0", lambda: self.zoom(reset=True))
        return menu

    def contextMenuEvent(self, event):
        if event.reason() == QContextMenuEvent.Reason.Mouse and self.quick_paste_click:
            event.accept()
            return
        self.open_context_menu(event.globalPos())
        event.accept()

    def open_context_menu(self, position):
        menu = self.create_context_menu()
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(position)

    def stop(self):
        self.stopping.set()
        self.blink_timer.stop()
        self.sender.close()


class TerminalResizeEdge(QWidget):
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self.edges)


class TerminalWindow(QMainWindow):
    def __init__(self, pty, tool, project, transfer=None, clipboard=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("ENGE SPX · " + tool + " · 智能粘贴终端")
        self.setObjectName("SmartTerminal")
        from .platform_ui import ASSETS
        from .ui.widgets import TitleBar
        self.setWindowIcon(QIcon(str(ASSETS / "app.ico")))
        self.resize(1180, 780)
        self.setMinimumSize(640, 400)
        self.setStyleSheet("""
QMainWindow#SmartTerminal { background: #1c1a18; }
QFrame#TerminalShell { background: #1c1a18; border: 1px solid #4a4239; }
QWidget { color: #e8e3dc; }
QWidget#TitleBar { background: #24221f; border-bottom: 1px solid #39352f; }
QLabel#Caption { color: #aaa296; font-size: 12px; }
QPushButton#WindowControl, QPushButton#WindowClose { background: transparent; border: none; border-radius: 4px; color: #aaa296; font-size: 16px; padding: 0; }
QPushButton#WindowControl:hover { color: #eee7dc; background: #39342e; }
QPushButton#WindowClose:hover { color: #fff0e5; background: #8b423b; }
QFrame#SessionBar { background: #24221f; border-bottom: 1px solid #39352f; }
QLabel#ToolBadge { color: #e5b194; background: #3a2e26; border: 1px solid #5e4333; border-radius: 5px; padding: 4px 10px; font-size: 12px; font-weight: 600; }
QLabel#ProjectName { color: #b8afa3; font-size: 12px; }
QLabel#ConnectionState { color: #91ad83; font-size: 11px; }
QToolButton#TerminalOptions { color: #aaa296; background: transparent; border: none; border-radius: 5px; font-size: 22px; }
QToolButton#TerminalOptions:hover { color: #f0d2bc; background: #39312a; }
QFrame#TerminalFooter { background: #24221f; border-top: 1px solid #39352f; }
QLabel#TerminalMessage { color: #b2a79b; font-size: 11px; }
QLabel#FontSize { color: #8e847a; font-size: 11px; }
QMenu#TerminalMenu { color: #e8e3dc; background: #2a2722; border: 1px solid #54483c; border-radius: 7px; padding: 5px; }
QMenu#TerminalMenu::item { padding: 7px 18px; border-radius: 4px; }
QMenu#TerminalMenu::item:selected { background: #4b382c; color: #f6dfcc; }
QMenu#TerminalMenu::item:disabled { color: #71685e; }
QMenu#TerminalMenu::separator { height: 1px; background: #423a31; margin: 5px 9px; }
QScrollBar:vertical { background: #1c1a18; width: 10px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: #53473d; min-height: 36px; border-radius: 4px; margin: 1px; }
QScrollBar::handle:vertical:hover { background: #7e604b; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
""")
        root = QFrame()
        root.setObjectName("TerminalShell")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.titlebar = TitleBar(self, "ENGE SPX  /  智能终端")
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSETS / "logo-64.png")).pixmap(QSize(20, 20)))
        self.titlebar.layout().insertWidget(0, logo)
        layout.addWidget(self.titlebar)
        session = QFrame()
        session.setObjectName("SessionBar")
        header = QHBoxLayout(session)
        header.setContentsMargins(16, 8, 8, 8)
        header.setSpacing(12)
        badge = QLabel({"codex": "Codex", "claude": "Claude Code", "shell": "Linux 终端"}.get(tool, tool))
        badge.setObjectName("ToolBadge")
        badge.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(badge)
        project_label = QLabel(project.name or str(project))
        project_label.setTextFormat(Qt.TextFormat.PlainText)
        project_label.setObjectName("ProjectName")
        project_label.setToolTip(str(project))
        project_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(project_label, 1)
        self.connection = QLabel("●  等待 CLI 输入区")
        self.connection.setObjectName("ConnectionState")
        header.addWidget(self.connection)
        options = QToolButton()
        options.setObjectName("TerminalOptions")
        options.setText("⋯")
        options.setFixedSize(32, 28)
        options.setAccessibleName("终端显示选项")
        options.setToolTip("字号与鼠标偏好；Shift+右键打开操作菜单")
        header.addWidget(options)
        layout.addWidget(session)
        self.view = TerminalView(pty, transfer, clipboard)
        layout.addWidget(self.view, 1)
        footer = QFrame()
        footer.setObjectName("TerminalFooter")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(16, 9, 16, 9)
        bottom.setSpacing(16)
        self.message = QLabel("单击定位 · 拖选自动复制 · 右键粘贴 · Shift+右键打开菜单")
        self.message.setObjectName("TerminalMessage")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        bottom.addWidget(self.message, 1)
        self.font_size = QLabel("11 pt  ·  UTF-8")
        self.font_size.setObjectName("FontSize")
        bottom.addWidget(self.font_size)
        layout.addWidget(footer)
        self.view.font_changed.connect(lambda size: self.font_size.setText(str(size) + " pt  ·  UTF-8"))
        self.view.status.connect(self.message.setText)
        self.view.readiness_changed.connect(lambda ready: self.connection.setText("●  输入区就绪" if ready else "●  等待 CLI 输入区"))
        self.view.ended.connect(self.connection_ended)
        options.clicked.connect(lambda: self.show_options(options))
        self.setCentralWidget(root)
        self.resize_edges = []
        for edges, cursor in ((Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor), (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor), (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor), (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor), (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor), (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor), (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor), (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor)):
            self.resize_edges.append(TerminalResizeEdge(self, edges, cursor))
        self.view.setFocus()

    def show_options(self, button):
        menu = QMenu(self)
        menu.setObjectName("TerminalMenu")
        menu.addAction("放大字号\tCtrl++", lambda: self.view.zoom(1))
        menu.addAction("缩小字号\tCtrl+-", lambda: self.view.zoom(-1))
        menu.addAction("重置字号\tCtrl+0", lambda: self.view.zoom(reset=True))
        menu.addSeparator()
        select = menu.addAction("拖选后自动复制")
        select.setCheckable(True)
        select.setChecked(self.view.copy_on_select)
        select.toggled.connect(lambda enabled: setattr(self.view, "copy_on_select", enabled))
        quick = menu.addAction("右键直接粘贴")
        quick.setCheckable(True)
        quick.setChecked(self.view.right_click_paste)
        quick.toggled.connect(lambda enabled: setattr(self.view, "right_click_paste", enabled))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h, b = self.width(), self.height(), 5
        positions = [(0, b, b, h - 2*b), (w - b, b, b, h - 2*b), (b, 0, w - 2*b, b), (b, h - b, w - 2*b, b), (0, 0, b, b), (w - b, 0, b, b), (0, h - b, b, b), (w - b, h - b, b, b)]
        for edge, position in zip(getattr(self, "resize_edges", []), positions):
            edge.setGeometry(*position)
            edge.setVisible(not self.isMaximized())
            edge.raise_()

    def connection_ended(self):
        self.view.stop()
        self.connection.setText("○  连接已结束")
        self.message.setText("终端连接已结束。工作区和持久资料按现有规则保留；可关闭此窗口。")

    def closeEvent(self, event):
        self.view.stop()
        event.accept()


def run(engine, project, tool, session, container):
    from pathlib import Path
    from .terminal_pty import DockerPTY
    app = QApplication.instance() or QApplication([])
    from .ui import style
    style.apply(app)
    command = engine.attach_command(project, tool, session, container, interactive=True, terminal_capabilities=True, terminal_relay=True)
    transfer = Transfer(engine, project, tool, session, container) if tool in ("claude", "codex") else None
    pty = DockerPTY(command, engine.docker.environment(), project)
    clipboard = WindowsClipboard() if os.name == "nt" else None
    window = TerminalWindow(pty, tool, Path(project), transfer, clipboard)
    def close_stopped_workspace():
        # The GUI's verified stop already ended this exec. Reclaim owned native
        # terminal windows on stop/exit without contacting or starting Docker.
        try:
            if engine.store.read("runtime.json", {}).get("phase") == "stopped":
                window.close()
        except SPXError:
            pass
    window.view.ended.connect(close_stopped_workspace)
    window.show()
    result = app.exec()
    window.view.stop()
    return result


def preview():
    from pathlib import Path
    from .terminal import discover
    from .terminal_pty import start
    app = QApplication.instance() or QApplication([])
    from .ui import style
    style.apply(app)
    shell = discover("powershell") if os.name == "nt" else "/bin/bash"
    if not shell:
        raise SPXError("未找到测试用命令行。")
    command = [shell, "-NoLogo", "-NoProfile"] if os.name == "nt" else [shell, "--noprofile", "--norc"]
    pty = start(command, dict(os.environ), str(Path.home()))
    window = TerminalWindow(pty, "终端测试（本机）", Path.home(), clipboard=WindowsClipboard() if os.name == "nt" else None)
    window.message.setText("仅测试本机终端显示与键盘；项目附件请在已核验的 Claude/Codex 工作区内测试。")
    window.show()
    return app.exec()
