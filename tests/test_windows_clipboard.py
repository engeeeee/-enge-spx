"""Native Windows API tests. These tests replace/empty the test desktop clipboard.

Use a disposable Windows test desktop; no personal clipboard backup is read.
No global input hook, SendInput, foreground window or window title lookup.
"""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest

from enge_spx.clipboard import WindowsClipboard


@unittest.skipUnless(os.name == "nt", "real Windows clipboard APIs")
class WindowsClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication, QWidget
        cls.app = QApplication.instance() or QApplication([])
        cls.owner = QWidget()
        cls.hwnd = int(cls.owner.winId())
        cls.clipboard = WindowsClipboard()
        cls.user = cls.clipboard.user
        cls.kernel = cls.clipboard.kernel
        cls.user.EmptyClipboard.restype = w.BOOL
        cls.user.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
        cls.user.SetClipboardData.restype = w.HANDLE
        cls.kernel.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
        cls.kernel.GlobalAlloc.restype = w.HANDLE
        cls.kernel.GlobalFree.argtypes = [w.HANDLE]

    def set_data(self, formats):
        deadline = time.monotonic() + 2
        while not self.user.OpenClipboard(self.hwnd):
            if time.monotonic() > deadline:
                self.fail("Test desktop clipboard remained unavailable")
            time.sleep(.01)
        try:
            self.assertTrue(self.user.EmptyClipboard())
            for fmt, value in formats:
                handle = self.kernel.GlobalAlloc(0x0042, len(value))  # GMEM_MOVEABLE | ZEROINIT
                self.assertTrue(handle)
                pointer = self.kernel.GlobalLock(handle)
                self.assertTrue(pointer)
                ctypes.memmove(pointer, value, len(value))
                self.kernel.GlobalUnlock(handle)
                if not self.user.SetClipboardData(fmt, handle):
                    self.kernel.GlobalFree(handle)
                    self.fail("SetClipboardData failed")
                # Ownership transferred to the OS, never GlobalFree here.
        finally:
            self.user.CloseClipboard()

    def tearDown(self):
        self.set_data([])

    def test_native_unicode_text_and_line_endings(self):
        text = "中文🦄\r\nline two\n最后一行"
        self.set_data([(13, (text + "\0").encode("utf-16-le"))])
        value = self.clipboard.read(self.clipboard.sequence())
        self.assertEqual((value.kind, value.value), ("text", text))

    def test_native_explorer_hdrop_multiple_unicode_files_wins_over_text(self):
        paths = (r"D:\项目\截图 一.png", r"C:\Users\Test\日志🦄.pdf")
        hdrop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + ("\0".join(paths) + "\0\0").encode("utf-16-le")
        self.set_data([(15, hdrop), (13, "preview\0".encode("utf-16-le"))])
        value = self.clipboard.read()
        self.assertEqual((value.kind, value.value), ("files", paths))

    def test_native_screenshot_dib_and_dibv5_become_png(self):
        for fmt, size, height in ((8, 40, 2), (17, 124, -2)):
            header = struct.pack("<IiiHHIIiiII", size, 2, height, 1, 24, 0, 16, 0, 0, 0, 0)
            value = header + b"\0" * (size - 40) + b"\x00\x00\xff\x00\xff\x00\0\0" * 2
            self.set_data([(fmt, value)])
            result = self.clipboard.read()
            self.assertEqual(result.kind, "image")
            self.assertTrue(result.value.startswith(b"\x89PNG"))

    def test_4k_dibv5_keeps_pixels_and_reports_snapshot_cost(self):
        import json
        from PySide6.QtGui import QImage
        width, height = 3840, 2160
        length = width * height * 4
        header = struct.pack("<IiiHHIIiiII", 124, width, -height, 1, 32, 3, length, 0, 0, 0, 0)
        header += struct.pack("<IIIII", 0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000, 0x73524742)
        header += b"\0" * (124 - len(header))
        self.set_data([(17, header + b"\x57\x77\xd9\xff" * (width * height))])
        started = time.perf_counter()
        snapshot = self.clipboard.read()
        elapsed = time.perf_counter() - started
        image = QImage.fromData(snapshot.value)
        self.assertEqual((image.width(), image.height()), (width, height))
        self.assertEqual(image.pixelColor(2000, 1000).name(), "#d97757")
        print(json.dumps({"measurement": "windows_clipboard_4k_dibv5_to_png", "width": width, "height": height, "milliseconds": round(elapsed * 1000, 2), "png_bytes": len(snapshot.value), "includes_docker_or_cli": False}), flush=True)

    def test_registered_png_format_and_empty_clipboard(self):
        from test_smart_clipboard import png
        self.set_data([(self.clipboard.png, png())])
        self.assertEqual(self.clipboard.read().kind, "image")
        self.set_data([])
        self.assertEqual(self.clipboard.read().kind, "empty")

    def test_changed_clipboard_is_cancelled_without_reading_new_content(self):
        from enge_spx.state import SPXError
        self.set_data([(13, "one\0".encode("utf-16-le"))])
        old = self.clipboard.sequence()
        self.set_data([(13, "two\0".encode("utf-16-le"))])
        with self.assertRaisesRegex(SPXError, "已改变"):
            self.clipboard.read(old)

    def test_intermediate_junction_is_rejected_before_read(self):
        import subprocess
        from enge_spx.clipboard_transfer import open_source
        from enge_spx.state import SPXError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outside").mkdir()
            (root / "outside" / "file.txt").write_text("synthetic", encoding="utf-8")
            # mklink is a cmd built-in; only fixed fixture paths are quoted by
            # list2cmdline here. No clipboard-derived command text is executed.
            created = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(root / "link"), str(root / "outside")], capture_output=True)
            self.assertEqual(created.returncode, 0)
            try:
                with self.assertRaises(SPXError):
                    with open_source(root / "link" / "file.txt"):
                        self.fail("intermediate junction followed")
            finally:
                os.rmdir(root / "link")

    def test_busy_native_clipboard_has_bounded_retry_and_releases_after_failure(self):
        import threading
        from enge_spx.state import SPXError
        failures = []
        self.assertTrue(self.user.OpenClipboard(self.hwnd))
        try:
            started = time.monotonic()
            def read():
                try:
                    self.clipboard.read()
                except SPXError:
                    failures.append("busy")
            thread = threading.Thread(target=read)
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, ["busy"])
            self.assertLess(time.monotonic() - started, 1)
        finally:
            self.user.CloseClipboard()
        self.set_data([(13, "recovered\0".encode("utf-16-le"))])
        self.assertEqual(self.clipboard.read().value, "recovered")


class OwnedPTYTests(unittest.TestCase):
    def test_owned_pty_preserves_native_ansi_and_truecolour_output(self):
        import codecs
        import sys
        import threading
        from enge_spx.terminal_pty import start
        from enge_spx.smart_terminal import TerminalScreen, TerminalStream
        code = '''import sys,os,time
if os.name=='nt':
 import ctypes
 k=ctypes.WinDLL('kernel32');k.SetConsoleOutputCP(65001)
 k.GetStdHandle.argtypes=[ctypes.c_ulong];k.GetStdHandle.restype=ctypes.c_void_p
 k.SetConsoleMode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
 k.SetConsoleMode(k.GetStdHandle(0xfffffff5),7)
sys.stdout.write('\\x1b[31mR\\x1b[0;38;2;12;34;56mT\\x1b[0;2mD\\x1b[0mSPX_COLOUR_DONE');sys.stdout.flush()
time.sleep(20)
'''
        with tempfile.TemporaryDirectory() as tmp:
            pty = start([sys.executable, "-u", "-c", code], dict(os.environ), tmp)
            screen = TerminalScreen(110, 32)
            stream = TerminalStream(screen)
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            lock = threading.Lock()
            def read():
                while block := pty.read():
                    with lock:
                        stream.feed(decoder.decode(block))
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    with lock:
                        found = [(row, x) for row in screen.buffer.values() for x in range(screen.columns - 17)
                                 if "".join(row[x + n].data for n in range(18)) == "RTDSPX_COLOUR_DONE"]
                    if found:
                        break
                    time.sleep(.01)
                self.assertTrue(found, "Native colour probe did not reach the owned terminal")
                row, x = found[0]
                self.assertNotEqual(row[x].fg, "default")
                self.assertEqual(row[x + 1].fg, "0c2238")
            finally:
                pty.close()
                reader.join(3)

    def test_owned_native_pty_receives_unicode_and_ctrl_sequences_without_shell(self):
        import sys
        import threading
        from enge_spx.terminal_pty import start
        code = '''import sys,os
if os.name=='nt':
 import ctypes
 k=ctypes.WinDLL('kernel32');k.SetConsoleCP(65001);k.SetConsoleOutputCP(65001)
 k.GetStdHandle.argtypes=[ctypes.c_ulong];k.GetStdHandle.restype=ctypes.c_void_p
 k.SetConsoleMode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
 k.SetConsoleMode(k.GetStdHandle(0xfffffff6),0x200)
else:
 import tty;tty.setraw(sys.stdin.fileno())
sys.stdout.write('SPX_READY\\x1b[?2004h');sys.stdout.flush()
data=bytearray()
while len(data)<4096:
 block=sys.stdin.buffer.read(1)
 if not block:break
 data.extend(block)
 if block==b'\\x16':break
data=bytes(data).replace(b'\\r\\n',b'\\n').replace(b'\\r',b'\\n')
sys.stdout.write('SPX_BYTES:'+data.hex());sys.stdout.flush()
'''
        with tempfile.TemporaryDirectory() as tmp:
            pty = start([sys.executable, "-u", "-c", code], dict(os.environ), tmp)
            output = bytearray()
            def read():
                while True:
                    block = pty.read()
                    if not block:
                        break
                    output.extend(block)
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 10
                while b"SPX_READY" not in output and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertIn(b"SPX_READY", output)
                data = "中文\nline\t🦄".encode() + b"\x1b[200~paste\nline2\x1b[201~\x16"
                pty.write(data)
                while b"SPX_BYTES:" + data.hex().encode() not in output and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertIn(b"SPX_BYTES:" + data.hex().encode(), output)
            finally:
                pty.close()
                reader.join(3)


if __name__ == "__main__":
    unittest.main()
