"""Bounded terminal row layouts; Qt objects stay on the GUI thread."""
from collections import OrderedDict
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QStaticText, QTransform, QImage, QPainter

from .terminal_render import BACKGROUND, FOREGROUND


class RowPainter:
    MAX_CELLS = 65536
    MAX_ROWS = 128
    MAX_RASTER_BYTES = 64 * 1024 * 1024

    @staticmethod
    def blit(painter, origin, image):
        mode = painter.compositionMode()
        if mode != QPainter.CompositionMode.CompositionMode_Source:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(origin, image)
        if mode != QPainter.CompositionMode.CompositionMode_Source:
            painter.setCompositionMode(mode)

    def __init__(self, font, width, height, color):
        self.font = QFont(font)
        self.width, self.height, self.color = width, height, color
        self.background = QColor(BACKGROUND)
        self.selection_bg, self.selection_fg = QColor("#654638"), QColor(FOREGROUND)
        self.rows, self.styles = OrderedDict(), {}
        self.rasters = OrderedDict()
        self.raster_bytes = self.raster_builds = 0
        self.cells = self.layout_builds = 0

    def set_background(self, color):
        color = QColor(color)
        if color.rgb() != self.background.rgb():
            self.rows.clear()
            self.rasters.clear()
            self.cells = self.raster_bytes = 0
        if color != self.background:
            self.styles.clear()
        self.background = color

    @staticmethod
    def compact(cells, selected):
        # Blank viewport padding has no ink. Keeping it in the raster key made
        # every one-column resize rebuild otherwise identical text bitmaps.
        end = len(cells)
        minimum = min(end, selected[1] + 1) if selected is not None else 0
        while end > minimum:
            char = cells[end - 1]
            if char.data != ' ' or char.bg != 'default' or char.reverse or char.underscore or char.strikethrough:
                break
            end -= 1
        return cells[:end]

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
        fg = QColor(fg)
        fg.setAlpha(255)  # Reverse video must not inherit background opacity.
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
        cells = self.compact(cells, selected)
        if not cells:
            return
        dpr = painter.device().devicePixelRatioF()
        dpi = painter.device().logicalDpiX(), painter.device().logicalDpiY()
        margin = math.ceil(2 * dpr)
        # Rasterize and blit at the same physical-pixel phase. Two logical
        # pixels are 2.5 physical pixels at 125%, which blurred the old cache.
        origin = QPointF((round(x * dpr) - margin) / dpr, round(y * dpr) / dpr)
        inset = margin / dpr
        key = cells, selected, dpr, dpi, self.background.rgba()
        if key in self.rasters:
            self.rasters.move_to_end(key)
            self.blit(painter, origin, self.rasters[key])
            return
        image = QImage(math.ceil(len(cells) * self.width * dpr) + 2 * margin, math.ceil(self.height * dpr),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.setDotsPerMeterX(round(painter.device().logicalDpiX() / .0254))
        image.setDotsPerMeterY(round(painter.device().logicalDpiY() / .0254))
        # Cache the actual composited row, not transparent text. Qt's fallback
        # glyph antialiasing (notably CJK) differs on a transparent destination.
        # Source-copying this row also avoids applying the tint twice.
        image.fill(self.background)
        row = QPainter(image)
        # Apply the integer-physical-pixel inset as a transform. Adding its
        # fractional logical value to glyph positions rounds CJK fallback
        # coordinates a second time inside Qt's fixed-point text engine.
        row.translate(inset, 0)
        fills, glyphs = self.layout(cells, selected)
        for left, width, color in fills:
            row.fillRect(QRectF(left, 0, width, self.height), color)
        for left, text, (fg, bg, font) in glyphs:
            row.setFont(font)
            row.setPen(fg)
            row.drawStaticText(QPointF(left, 0), text)
        row.end()
        self.raster_builds += 1
        size = image.sizeInBytes()
        if size <= self.MAX_RASTER_BYTES:
            self.rasters[key] = image
            self.raster_bytes += size
            while len(self.rasters) > self.MAX_ROWS or self.raster_bytes > self.MAX_RASTER_BYTES:
                _, old = self.rasters.popitem(last=False)
                self.raster_bytes -= old.sizeInBytes()
        self.blit(painter, origin, image)
