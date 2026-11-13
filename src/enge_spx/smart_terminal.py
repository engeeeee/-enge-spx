"""Native Qt terminal: local paste events -> the existing CLI's owned ConPTY.

This is a terminal display, not a replacement chat composer or CLI protocol.
The CLI owns its input buffer, editing, history, attachments and submission.
"""
from __future__ import annotations

from concurrent.futures import Future
from collections import Counter
from copy import deepcopy
import codecs
import os
import queue
import re
import threading
import time

import pyte
from PySide6.QtCore import Qt, QTimer, Signal, QEvent, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollBar, QPushButton

from .clipboard import WindowsClipboard
from .clipboard_transfer import Transfer, text_frame
from .state import SPXError


class TerminalScreen(pyte.HistoryScreen):
    def __init__(self, columns, lines, respond=lambda data: None):
        self.respond = respond
        self.primary = None
        super().__init__(columns, lines, history=2000)

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

    def wait(self, ticket, cancelled, timeout=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while not cancelled.is_set():
                if any(count > ticket[number] for number, count in self.counts.items()):
                    return True
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.condition.wait(min(left, .2))
        return False


class OrderedInput:
    """One writer preserves typing/paste/Enter order even during a large copy."""
    def __init__(self, pty, transfer, report, ready, images=None):
        self.pty, self.transfer, self.report, self.ready = pty, transfer, report, ready
        self.queue = queue.Queue(maxsize=2048)
        self.images = images
        self.closed = threading.Event()
        self.pastes = threading.BoundedSemaphore(8)
        self.thread = threading.Thread(target=self._run, name="spx-terminal-input", daemon=True)
        self.thread.start()

    def put(self, kind, value):
        if self.closed.is_set():
            return False
        try:
            self.queue.put_nowait((kind, value))
        except queue.Full:
            self.report("输入队列已满，请稍候；本次输入未发送。")
            return False
        return True

    def _run(self):
        failed_paste = False
        while not self.closed.is_set():
            try:
                kind, value = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                if kind == "keys":
                    if failed_paste and value == b"\r":
                        self.report("上次粘贴失败，已取消这次回车。输入仍保留；检查后可再次回车。")
                        failed_paste = False
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
                            ticket = self.images.ticket() if image and self.images else None
                            self.pty.write(frame)
                            # Separate native paste events; no Enter, clearing,
                            # hotkey injection or new CLI process is involved.
                            if ticket is not None and not self.images.wait(ticket, self.closed):
                                raise SPXError("CLI 未确认原生图片附件。请检查输入区是否出现 [Image #N]；若只显示路径，请删除该路径并确认模型支持图片后重试。本次排队的回车将取消。")
                            time.sleep(.02)
                        self.report("附件已交给 CLI；请检查原生图片标记或文件引用，再自行发送。")
                    failed_paste = False
            except SPXError as error:
                self.report(str(error))
                failed_paste = True
            except Exception:
                # Do not propagate raw clipboard/OS/CLI errors into logs/UI.
                self.report("粘贴或输入未完成。当前草稿保留；请检查文件权限、大小、CLI 版本和工作区连接后重试。")
                failed_paste = True
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
                kind, value = self.queue.get_nowait()
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
        self.screen = TerminalScreen(110, 32, lambda data: self.sender.put("keys", data))
        self.stream = pyte.Stream(self.screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.output = queue.Queue(maxsize=64)
        self.pending = threading.Event()
        self.stopping = threading.Event()
        self.wake.connect(self._drain)
        self.font = QFont("Cascadia Mono" if os.name == "nt" else "DejaVu Sans Mono", 11)
        self.font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(self.font)
        self.metrics = QFontMetricsF(self.font)
        self.cell_width = self.metrics.horizontalAdvance("M")
        self.cell_height = self.metrics.height() + 2
        self.selection = None
        self.selecting = False
        self.preedit = ""
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
        if self.screen.bracketed:
            self.ready.set()
        else:
            self.ready.clear()
        if changed:
            self.images.observe("".join("".join(self.screen.buffer[y][x].data for x in range(self.screen.columns)) for y in range(self.screen.lines)))
        self.scrollbar.setRange(0, len(self.screen.history.top))
        if self.offset == 0:
            self.scrollbar.setValue(self.scrollbar.maximum())
        if changed:
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
            self.update(QRectF(8 + cursor.x * self.cell_width, 4 + cursor.y * self.cell_height, self.cell_width, self.cell_height).toAlignedRect())

    def _scroll(self, value):
        self.offset = self.scrollbar.maximum() - value
        self.update()

    def rows(self):
        current = [self.screen.buffer[y] for y in range(self.screen.lines)]
        if not self.offset:
            return current
        lines = [*self.screen.history.top, *current]
        end = len(lines) - self.offset
        return lines[max(0, end - self.screen.lines):end]

    def _color(self, value, foreground=True):
        key = (value, foreground)
        if key in self.colors:
            return self.colors[key]
        named = {"default": "#e8e3dc" if foreground else "#1c1a18", "black": "#24211f", "red": "#e47b71", "green": "#a3bf89", "brown": "#d6ad70", "blue": "#91aace", "magenta": "#c6a0c7", "cyan": "#87bbb6", "white": "#ded8cf", "brightblack": "#8b8179", "brightred": "#f49b90", "brightgreen": "#c0d6a4", "brightbrown": "#f0cc93", "brightblue": "#b7cbee", "brightmagenta": "#dec0e1", "brightcyan": "#b5e2dc", "brightwhite": "#ffffff"}
        result = QColor(named.get(value, "#" + value if re.fullmatch("[a-fA-F0-9]{6}", value) else named["default"]))
        if len(self.colors) >= 512:
            self.colors.clear()
        self.colors[key] = result
        return result

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1c1a18"))
        p.setFont(self.font)
        selected = sorted(self.selection) if self.selection else None
        clip = event.rect()
        for y, line in enumerate(self.rows()):
            if 4 + (y + 1) * self.cell_height < clip.top() or 4 + y * self.cell_height > clip.bottom():
                continue
            glyphs = []
            for x in range(self.screen.columns):
                if 8 + (x + 1) * self.cell_width < clip.left() or 8 + x * self.cell_width > clip.right():
                    continue
                char = line[x]
                rectangle = QRectF(8 + x * self.cell_width, 4 + y * self.cell_height, self.cell_width, self.cell_height)
                fg, bg = self._color(char.fg), self._color(char.bg, False)
                if char.reverse:
                    fg, bg = bg, fg
                if selected and selected[0] <= (y, x) <= selected[1]:
                    bg = QColor("#654638")
                if bg != QColor("#1c1a18"):
                    p.fillRect(rectangle, bg)
                if char.data and char.data != " ":
                    glyphs.append((rectangle, char, fg))
            # Paint wide glyphs after ALL cell backgrounds, so a CJK character
            # cannot have its second half erased by the continuation cell.
            for rectangle, char, fg in glyphs:
                    key = (char.bold, char.italics, char.underscore)
                    font = self.fonts.get(key)
                    if font is None:
                        font = QFont(self.font)
                        font.setBold(char.bold)
                        font.setItalic(char.italics)
                        font.setUnderline(char.underscore)
                        self.fonts[key] = font
                    p.setFont(font)
                    p.setPen(fg)
                    p.drawText(rectangle.left(), rectangle.top() + self.metrics.ascent(), char.data)
        cursor = self.screen.cursor
        if self.blink and self.offset == 0 and not cursor.hidden:
            p.fillRect(QRectF(8 + cursor.x * self.cell_width, 4 + cursor.y * self.cell_height, 2, self.cell_height), QColor("#d89979"))
        if self.preedit:
            p.setPen(QColor("#e8e3dc"))
            p.drawText(8 + cursor.x * self.cell_width, 4 + (cursor.y + 1) * self.cell_height, self.preedit)

    def resizeEvent(self, event):
        self.scrollbar.setGeometry(self.width() - 14, 0, 14, self.height())
        columns = max(20, int((self.width() - 30) / self.cell_width))
        rows = max(5, int((self.height() - 8) / self.cell_height))
        self.screen.resize(lines=rows, columns=columns)
        self.pty.resize(columns, rows)
        self.selection = None

    def paste(self):
        if self.stopping.is_set():
            self.status.emit("终端连接已结束，请从 ENGE SPX 重新打开工具后粘贴。")
            return
        if self.clipboard is None:
            self.status.emit("系统剪贴板桥接仅在 Windows 中启用。")
            return
        self.offset = 0
        self.sender.paste(self.clipboard)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste) or (event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.paste()
            event.accept()
            return
        ctrl_c = event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if (self.selection and (event.matches(QKeySequence.StandardKey.Copy) or ctrl_c)) or (ctrl_c and event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.copy()
            return
        self.selection = None
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
        self.update()
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            cursor = self.screen.cursor
            return QRectF(8 + cursor.x * self.cell_width, 4 + cursor.y * self.cell_height, self.cell_width, self.cell_height).toRect()
        if query == Qt.InputMethodQuery.ImFont:
            return self.font
        return super().inputMethodQuery(query)

    def cell(self, event):
        return (max(0, min(self.screen.lines - 1, int((event.position().y() - 4) / self.cell_height))),
                max(0, min(self.screen.columns - 1, int((event.position().x() - 8) / self.cell_width))))

    def mousePressEvent(self, event):
        self.setFocus()
        y, x = self.cell(event)
        if self.screen.mouse and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            button = {Qt.MouseButton.LeftButton: 0, Qt.MouseButton.MiddleButton: 1, Qt.MouseButton.RightButton: 2}.get(event.button(), 0)
            self.sender.put("keys", f"\x1b[<{button};{x+1};{y+1}M".encode())
            self.selecting = False
        elif event.button() == Qt.MouseButton.LeftButton:
            self.selection = ((y, x), (y, x))
            self.selecting = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.paste()

    def mouseMoveEvent(self, event):
        if self.selecting:
            self.selection = (self.selection[0], self.cell(event))
            self.update()
        elif self.screen.mouse and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            motion = (1003 << 5) in self.screen.mode or ((1002 << 5) in self.screen.mode and event.buttons())
            if motion:
                y, x = self.cell(event)
                button = 0 if event.buttons() & Qt.MouseButton.LeftButton else 2 if event.buttons() & Qt.MouseButton.RightButton else 3
                self.sender.put("keys", f"\x1b[<{32+button};{x+1};{y+1}M".encode())

    def mouseReleaseEvent(self, event):
        if self.screen.mouse and not self.selecting and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            y, x = self.cell(event)
            button = {Qt.MouseButton.LeftButton: 0, Qt.MouseButton.MiddleButton: 1, Qt.MouseButton.RightButton: 2}.get(event.button(), 0)
            self.sender.put("keys", f"\x1b[<{button};{x+1};{y+1}m".encode())
        self.selecting = False

    def wheelEvent(self, event):
        if self.screen.mouse and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            y, x = self.cell(event)
            self.sender.put("keys", f"\x1b[<{64 if event.angleDelta().y()>0 else 65};{x+1};{y+1}M".encode())
        else:
            self.scrollbar.setValue(self.scrollbar.value() - event.angleDelta().y() // 40)

    def copy(self):
        if not self.selection:
            return
        (y1, x1), (y2, x2) = sorted(self.selection)
        lines = self.rows()
        text = []
        for y in range(y1, y2 + 1):
            left, right = (x1 if y == y1 else 0), (x2 + 1 if y == y2 else self.screen.columns)
            text.append("".join(lines[y][x].data for x in range(left, right)).rstrip())
        QGuiApplication.clipboard().setText("\n".join(text))
        self.status.emit("已复制所选终端文字。")

    def stop(self):
        self.stopping.set()
        self.blink_timer.stop()
        self.sender.close()


class TerminalWindow(QMainWindow):
    def __init__(self, pty, tool, project, transfer=None, clipboard=None):
        super().__init__()
        self.setWindowTitle("ENGE SPX · " + tool + " · 智能粘贴终端")
        from .platform_ui import ASSETS
        self.setWindowIcon(QIcon(str(ASSETS / "app.ico")))
        self.resize(1120, 760)
        self.setStyleSheet("QMainWindow,QWidget{background:#1c1a18;color:#e8e3dc} QLabel{padding:6px} QPushButton{background:#3b302a;border:1px solid #695044;border-radius:5px;padding:5px 12px} QScrollBar:vertical{background:#23201d;width:12px} QScrollBar::handle:vertical{background:#574b42;min-height:24px}")
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 4, 8, 4)
        header = QHBoxLayout()
        header.addWidget(QLabel(tool + "  /  " + project.name), 1)
        copy = QPushButton("复制 Ctrl+Shift+C")
        header.addWidget(copy)
        layout.addLayout(header)
        self.view = TerminalView(pty, transfer, clipboard)
        copy.clicked.connect(self.view.copy)
        layout.addWidget(self.view, 1)
        self.message = QLabel("Ctrl+V 粘贴文字、截图或文件 · 由 CLI 保留草稿，按 Enter 才发送")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.view.status.connect(self.message.setText)
        self.view.ended.connect(self.connection_ended)
        self.setCentralWidget(root)
        self.view.setFocus()

    def connection_ended(self):
        self.view.stop()
        self.message.setText("终端连接已结束。工作区和持久资料按现有规则保留；可关闭此窗口。")

    def closeEvent(self, event):
        self.view.stop()
        event.accept()


def run(engine, project, tool, session, container):
    from pathlib import Path
    from .terminal_pty import start
    app = QApplication.instance() or QApplication([])
    command = engine.attach_command(project, tool, session, container, interactive=True)
    transfer = Transfer(engine, project, tool, session, container) if tool in ("claude", "codex") else None
    pty = start(command, engine.docker.environment(), project)
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
    shell = discover("powershell") if os.name == "nt" else "/bin/bash"
    if not shell:
        raise SPXError("未找到测试用命令行。")
    command = [shell, "-NoLogo", "-NoProfile"] if os.name == "nt" else [shell, "--noprofile", "--norc"]
    pty = start(command, dict(os.environ), str(Path.home()))
    window = TerminalWindow(pty, "终端测试（本机）", Path.home(), clipboard=WindowsClipboard() if os.name == "nt" else None)
    window.message.setText("仅测试本机终端显示与键盘；项目附件请在已核验的 Claude/Codex 工作区内测试。")
    window.show()
    return app.exec()
