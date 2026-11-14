"""Bounded terminal row layouts; Qt objects stay on the GUI thread."""
from collections import OrderedDict

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QStaticText, QTransform

from .terminal_render import BACKGROUND, FOREGROUND


class RowPainter:
    MAX_CELLS = 32768
    MAX_ROWS = 128

    def __init__(self, font, width, height, color):
        self.font = QFont(font)
        self.width, self.height, self.color = width, height, color
        self.background = QColor(BACKGROUND)
        self.selection_bg, self.selection_fg = QColor("#654638"), QColor(FOREGROUND)
        self.rows, self.styles = OrderedDict(), {}
        self.cells = self.layout_builds = 0

    def style(self, char, selected):
        key = (*char[1:], selected)
        cached = self.styles.get(key)
        if cached is not None:
            return cached
        fg, bg = self.color(char.fg), self.color(char.bg, False)
        if char.reverse:
            fg, bg = bg, fg
        if getattr(char, "faint", False):
            fg = QColor(*(round(a * .58 + b * .42) for a, b in zip(fg.getRgb()[:3], bg.getRgb()[:3])))
        if selected:
            fg, bg = self.selection_fg, self.selection_bg
        font = QFont(self.font)
        font.setBold(char.bold)
        font.setItalic(char.italics)
        font.setUnderline(char.underscore)
        font.setStrikeOut(char.strikethrough)
        cached = (fg, bg, font)
        if len(self.styles) >= 512:
            self.styles.clear()
        self.styles[key] = cached
        return cached

    def layout(self, cells, selected):
        key = cells, selected
        if key in self.rows:
            self.rows.move_to_end(key)
            return self.rows[key]
        fills, glyphs = [], []
        last_bg, bg_start = self.background, 0
        text, text_start, text_style = [], 0, None

        def flush():
            if text and not all(c == " " for c in text):
                block = QStaticText("".join(text))
                block.setTextFormat(Qt.TextFormat.PlainText)
                block.prepare(QTransform(), text_style[2])
                glyphs.append((text_start * self.width, block, text_style))
            text.clear()

        for x, char in enumerate(cells):
            style = self.style(char, selected is not None and selected[0] <= x <= selected[1])
            fg, bg, font = style
            if bg != last_bg:
                if last_bg != self.background:
                    fills.append((bg_start * self.width, (x - bg_start) * self.width, last_bg))
                last_bg, bg_start = bg, x
            # Printable ASCII has an exact one-cell advance. Keep CJK,
            # combining clusters and emoji at their individual grid positions.
            ascii_cell = len(char.data) == 1 and " " <= char.data <= "~"
            if not ascii_cell or (text and (style != text_style or x != text_start + len(text))):
                flush()
            if char.data:
                if not text:
                    text_start, text_style = x, style
                text.append(char.data)
                if not ascii_cell:
                    flush()
        flush()
        if last_bg != self.background:
            fills.append((bg_start * self.width, (len(cells) - bg_start) * self.width, last_bg))
        result = fills, glyphs
        self.layout_builds += 1
        self.rows[key] = result
        self.cells += len(cells)
        while len(self.rows) > self.MAX_ROWS or self.cells > self.MAX_CELLS:
            old, _ = self.rows.popitem(last=False)
            self.cells -= len(old[0])
        return result

    def draw(self, painter, cells, selected, x, y):
        fills, glyphs = self.layout(cells, selected)
        for left, width, color in fills:
            painter.fillRect(QRectF(x + left, y, width, self.height), color)
        for left, text, (fg, bg, font) in glyphs:
            painter.setFont(font)
            painter.setPen(fg)
            painter.drawStaticText(QPointF(x + left, y), text)
