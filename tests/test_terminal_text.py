"""Differential semantic proof for the conservative ASCII fast path."""
import random
import unittest
import pyte
from enge_spx.smart_terminal import TerminalScreen, TerminalStream


class ReferenceScreen(TerminalScreen):
    draw = pyte.Screen.draw


class TerminalTextTests(unittest.TestCase):
    def test_mixed_vt_matches_unmodified_pyte_through_wrap_charset_insert_and_unicode(self):
        actual, reference = TerminalScreen(35, 9), ReferenceScreen(35, 9)
        streams = [TerminalStream(actual), TerminalStream(reference)]
        operations = ['ASCII const result = 42;', '中文 mixed e\u0301 🙂', '🧑\u200d💻 after joiner',
                      '\ufe0f after selector', '\u0301 combining', '\r\n', '\t', '\x1b[2J', '\x1b[H',
                      '\x1b[4hinsert\x1b[4l', '\x1b[?7lautowrap off\x1b[?7h',
                      '\x1b(0lqqqk\x1b(B', '\x1b[31;2mred faint\x1b[0m', '\x1b[38;2;1;2;3mRGB\x1b[0m',
                      '\x1b[3;30H边界 edge and wrapping', '\x1b[2;8r\x1b[8;1Hscroll\n\x1b[r', '\x1b[2P', '\x1b[3@']
        randomizer = random.Random(142025)
        for index in range(500):
            text = randomizer.choice(operations)
            for stream in streams:
                stream.feed(text)
            for row in range(actual.lines):
                self.assertEqual([actual.buffer[row].get(column, actual.default_char) for column in range(actual.columns)],
                                 [reference.buffer[row].get(column, reference.default_char) for column in range(reference.columns)],
                                 (index, row, repr(text)))
            self.assertEqual((actual.cursor.x, actual.cursor.y, actual.cursor.attrs),
                             (reference.cursor.x, reference.cursor.y, reference.cursor.attrs))
            self.assertEqual([dict(row) for row in actual.history.top], [dict(row) for row in reference.history.top])
        self.assertLessEqual(len(actual.ascii_tables), 64)
