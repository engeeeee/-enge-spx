"""Terminal colour negotiation and bounded VT extensions around unmodified pyte."""
from collections import namedtuple
import re
import time

import pyte

BACKGROUND = "#1c1a18"
FOREGROUND = "#e8e3dc"
PALETTE = {
    "black": "#24211f", "red": "#e47b71", "green": "#a3bf89", "brown": "#d6ad70",
    "blue": "#91aace", "magenta": "#c6a0c7", "cyan": "#87bbb6", "white": "#ded8cf",
    "brightblack": "#8b8179", "brightred": "#f49b90", "brightgreen": "#c0d6a4", "brightbrown": "#f0cc93",
    "brightblue": "#b7cbee", "brightmagenta": "#dec0e1", "brightcyan": "#b5e2dc", "brightwhite": "#ffffff",
}
TerminalChar = namedtuple("TerminalChar", [*pyte.screens.Char._fields, "faint"],
                          defaults=[*pyte.screens.Char._field_defaults.values(), False])


def sgr_attributes(attrs, faint):
    """Keep SGR 2/22 while leaving RGB component values to pyte unchanged."""
    result, index = [], 0
    while index < len(attrs):
        value = attrs[index]
        if value == 2:
            faint = True
        else:
            if value in (0, 22):
                faint = False
            result.append(value)
            if value in (38, 48, 58) and index + 1 < len(attrs):
                mode = attrs[index + 1]
                count = 4 if mode == 2 else 2 if mode == 5 else 1
                result.extend(attrs[index + 1:index + 1 + count])
                index += count
        index += 1
    return result, faint


class TerminalStream:
    """Handle common colour queries and colon SGR; no OSC52 or host access.

    Keep escape sequences intact across output reads. Bound incomplete OSC/CSI
    buffers so a child cannot grow host memory with an unterminated sequence.
    """
    def __init__(self, screen, frame_complete=None):
        self.screen = screen
        self.stream = pyte.Stream(screen)
        self.pending = ""
        self.discard_osc = False
        self.synchronized_at = None
        self.frame_complete = frame_complete
        self.frame_serial = 0

    def expire_synchronized_update(self):
        self.synchronized_at = None
        self.screen.reset_mode(2026, private=True)

    def _csi(self, sequence):
        if sequence == '\x1b[?2026$p':
            state = 1 if self.synchronized_at is not None else 2
            self.screen.respond(f'\x1b[?2026;{state}$y'.encode())
            return ''
        match = re.fullmatch(r'\x1b\[\?([0-9;]+)([hl])', sequence)
        if match and '2026' in match[1].split(';'):
            if match[2] == 'h':
                if self.synchronized_at is None:
                    self.synchronized_at = time.monotonic()
            else:
                self.synchronized_at = None
                self.frame_serial += 1
        return self._sgr(sequence) if sequence.endswith('m') and ':' in sequence else sequence

    @staticmethod
    def _rgb(color):
        color = color.lstrip("#")
        return "/".join(color[i:i + 2] * 2 for i in (0, 2, 4))

    def _osc(self, payload):
        if payload in ("10;?", "11;?"):
            color = FOREGROUND if payload.startswith("10;") else getattr(self.screen, "terminal_background", BACKGROUND)
            self.screen.respond(("\x1b]" + payload[:2] + ";rgb:" + self._rgb(color) + "\x1b\\").encode())
        elif re.fullmatch(r"4;(?:[0-9]{1,3});\?", payload):
            index = int(payload.split(";")[1])
            if index < 16:
                color = list(PALETTE.values())[index]
            elif index < 232:
                n = index - 16
                levels = (0, 95, 135, 175, 215, 255)
                color = "#{:02x}{:02x}{:02x}".format(levels[n // 36], levels[n // 6 % 6], levels[n % 6])
            elif index < 256:
                color = "#{0:02x}{0:02x}{0:02x}".format(8 + (index - 232) * 10)
            else:
                return
            self.screen.respond(("\x1b]4;" + str(index) + ";rgb:" + self._rgb(color) + "\x1b\\").encode())
        elif payload.startswith(("0;", "1;", "2;")):
            self.stream.feed("\x1b]" + payload + "\x07")
        # Other OSC, including clipboard writes/reads, are intentionally ignored.

    @staticmethod
    def _sgr(sequence):
        parts = sequence[2:-1].split(";")
        normalized = []
        for part in parts:
            values = part.split(":")
            if len(values) == 1:
                normalized.append(part)
            elif values[0] in ("38", "48", "58") and len(values) >= 3:
                if values[1] == "2" and len(values) in (5, 6):
                    normalized.extend([values[0], "2", *values[-3:]])
                elif values[1] == "5" and len(values) == 3:
                    normalized.extend(values)
            elif values[0] == "4":
                normalized.append("24" if values[1] == "0" else "4")
        return "\x1b[" + ";".join(normalized) + "m"

    def feed(self, text):
        text = self.pending + text
        self.pending = ""
        index, plain = 0, []
        while index < len(text):
            if self.discard_osc:
                end = re.search(r"\x07|\x1b\\|\x9c", text[index:])
                if end is None:
                    self.pending = "\x1b" if text.endswith("\x1b") else ""
                    break
                index += end.end()
                self.discard_osc = False
                continue
            start = text.find("\x1b", index)
            if start < 0:
                plain.append(text[index:])
                break
            plain.append(text[index:start])
            if start + 1 == len(text):
                self.pending = text[start:]
                break
            kind = text[start + 1]
            if kind == "]":
                end = re.search(r"\x07|\x1b\\|\x9c", text[start + 2:])
                if end is None:
                    if len(text) - start <= 4096:
                        self.pending = text[start:]
                    else:
                        self.discard_osc = True
                        self.pending = "\x1b" if text.endswith("\x1b") else ""
                    break
                if plain:
                    self.stream.feed("".join(plain))
                    plain = []
                if end.start() <= 4096:
                    self._osc(text[start + 2:start + 2 + end.start()])
                index = start + 2 + end.end()
            elif kind == "[":
                end = re.search(r"[@-~]", text[start + 2:])
                if end is None:
                    self.pending = text[start:] if len(text) - start <= 256 else ""
                    break
                index = start + 2 + end.end()
                sequence = text[start:index]
                if len(sequence) <= 256:
                    serial = self.frame_serial
                    plain.append(self._csi(sequence))
                    if self.frame_serial != serial and self.frame_complete is not None:
                        self.stream.feed(''.join(plain))
                        plain = []
                        self.frame_complete()
            else:
                plain.append(text[start:start + 2])
                index = start + 2
        if plain:
            self.stream.feed("".join(plain))
