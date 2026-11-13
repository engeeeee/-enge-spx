"""Clipboard/PTY integration boundaries; no accounts or external network."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication
import pyte

from enge_spx import terminal
from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.clipboard import Snapshot, dib_to_bmp, png_image, MAX_PIXELS
from enge_spx.clipboard_transfer import Attachment, InputAdapter, Transfer, open_source, text_frame, validate_image
from enge_spx.smart_terminal import ImageAcknowledgement, OrderedInput, TerminalScreen, TerminalWindow, key_bytes
from enge_spx.clipboard_cache import CacheLease, RETENTION
from enge_spx.state import SPXError, Store


def png():
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(QColor("#d97757"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(data)


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    if not predicate():
        raise AssertionError("Owned input worker did not finish")


class ClipboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unicode_multiline_is_one_bracketed_paste_without_files_or_enter(self):
        text = "第一行\r\n第二行\nhello 👋 café\tend"
        self.assertEqual(text_frame(text), b"\x1b[200~" + text.encode() + b"\x1b[201~")
        self.assertFalse(text_frame(text).endswith(b"\r"))

    def test_clipboard_cannot_break_out_of_paste_with_escape_sequences(self):
        frame = text_frame("a\x1b[201~\r危险\x00\x7f")
        self.assertEqual(frame.count(b"\x1b[201~"), 1)
        self.assertNotIn(b"\x00", frame)

    def test_dib_24bit_and_v5_top_down_bitmap(self):
        for size, height in ((40, 2), (124, -2)):
            header = struct.pack("<IiiHHIIiiII", size, 2, height, 1, 24, 0, 16, 0, 0, 0, 0)
            data = header + b"\0" * (size - 40) + b"\x00\x00\xff\x00\xff\x00\0\0" * 2
            self.assertTrue(dib_to_bmp(data).startswith(b"BM"))
            self.assertTrue(png_image(data, dib=True).startswith(b"\x89PNG"))

    def test_dib_bitfield_offset_includes_three_masks(self):
        data = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 32, 3, 4, 0, 0, 0, 0) + struct.pack("<III", 0xff0000, 0xff00, 0xff) + b"\0\0\xff\0"
        self.assertEqual(struct.unpack_from("<I", dib_to_bmp(data), 10)[0], 66)

    def test_invalid_and_oversized_bitmaps_fail_before_decoding(self):
        for data in (b"bad", struct.pack("<IiiHHIIiiII", 40, MAX_PIXELS, 10, 1, 24, 0, 0, 0, 0, 0, 0)):
            with self.assertRaises(SPXError):
                dib_to_bmp(data)

    def test_png_reencodes_valid_pixels_and_rejects_corruption(self):
        self.assertTrue(png_image(png()).startswith(b"\x89PNG"))
        with self.assertRaises(SPXError):
            png_image(b"not an image")

    def test_jpeg_and_webp_files_are_real_decodable_images(self):
        image = QImage(48, 32, QImage.Format.Format_RGB32)
        image.fill(QColor("#87bbb6"))
        for fmt in ("JPEG", "WEBP"):
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            self.assertTrue(image.save(buffer, fmt))
            raw = bytes(data)
            self.assertEqual(validate_image(io.BytesIO(raw), len(raw)).read(), raw)

    def test_disguised_svg_never_enters_a_host_svg_or_external_resource_decoder(self):
        raw = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///must-not-read-host-file"/></svg>'
        with patch("PySide6.QtGui.QImageReader", side_effect=AssertionError("unexpected image decoder")):
            with self.assertRaises(SPXError):
                validate_image(io.BytesIO(raw), len(raw), b"png")
        raw = png()
        with self.assertRaisesRegex(SPXError, "扩展名"):
            validate_image(io.BytesIO(raw), len(raw), b"jpeg")

    def test_each_native_image_gets_a_separate_paste_event(self):
        prefix = "/workspace/" + "a" * 16 + "/.enge-spx-clipboard/" + "b" * 32 + "/"
        images = [Attachment(prefix + c * 32 + ".png", True) for c in ("c", "d")]
        for tool, version in (("claude", (2, 1, 319)), ("codex", (0, 167, 0))):
            frames = InputAdapter(tool, version).frames(images)
            self.assertEqual(len(frames), 2)
            self.assertEqual(frames, [text_frame(x.path) for x in images])

    def test_regular_files_are_references_not_fake_vision_attachments(self):
        path = "/tmp/enge-spx-clipboard-" + "a" * 16 + "/" + "b" * 32 + "/" + "c" * 32 + ".pdf"
        file = Attachment(path, False)
        self.assertEqual(InputAdapter("claude", ()).frames([file]), [text_frame(" @" + path + " ")])
        self.assertEqual(InputAdapter("codex", ()).frames([file]), [text_frame(" " + path + " ")])
        self.assertEqual(InputAdapter("codex", (999, 0, 0)).frames([Attachment(path, True)]), [text_frame(path)])

    def test_adapter_rejects_escaped_or_unowned_attachment_paths(self):
        for path in ("/etc/passwd", "/workspace/../../secret.png", "a\nrm -rf /", "/tmp/a.png"):
            with self.assertRaises(SPXError):
                InputAdapter("claude", (2, 1, 319)).frames([Attachment(path, False)])

    def test_original_names_label_files_without_corrupting_native_image_paste(self):
        prefix = "/workspace/" + "a" * 16 + "/.enge-spx-clipboard/" + "b" * 32 + "/"
        adapter = InputAdapter("codex", (0, 167, 0))
        events = adapter.events([Attachment(prefix + "c" * 32 + ".png", True, "截图 🦄.png"), Attachment(prefix + "d" * 32 + ".txt", False, "日志.txt")])
        self.assertEqual([image for data, image in events], [False, True, False])
        self.assertIn("截图 🦄.png".encode(), events[0][0])
        self.assertEqual(events[1][0], text_frame(prefix + "c" * 32 + ".png"))
        self.assertIn("日志.txt".encode(), events[2][0])

    def test_source_files_unicode_and_size_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "日志 🐈.txt"
            file.write_text("中文", encoding="utf-8")
            with open_source(file) as (stream, size):
                self.assertEqual(stream.read(), "中文".encode())
                self.assertEqual(size, 6)
            with file.open("wb") as out:
                out.truncate(129 * 1024 * 1024)
            with self.assertRaises(SPXError):
                with open_source(file):
                    self.fail("oversized file accepted")

    @unittest.skipIf(os.name == "nt", "POSIX source descriptors")
    def test_symlink_directory_and_fifo_sources_do_not_block_or_follow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real").write_bytes(b"private")
            (root / "link").symlink_to(root / "real")
            os.mkfifo(root / "fifo")
            for source in (root / "link", root, root / "fifo"):
                with self.assertRaises((OSError, SPXError)):
                    with open_source(source):
                        self.fail("non-regular source accepted")


@unittest.skipIf(os.name == "nt", "Linux container dir_fd operations")
class ContainerImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.temp = self.base / "tmp"
        self.temp.mkdir()
        self.key, self.bridge = "a" * 16, "b" * 32
        self.project = self.workspace / self.key
        self.project.mkdir()
        spec = importlib.util.spec_from_file_location("clipboard_container_fixture", PACKAGE_RESOURCES / "checks/clipboard_transfer.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def packet(self, data=(b"PDF synthetic", b"print('hi')"), access="rw", digest=True):
        self.files = [{"name": c * 32 + ext, "size": len(value)} for c, ext, value in zip(("c", "d"), (".pdf", ".py"), data)]
        header = {"schema": 1, "project": self.key, "access": access, "bridge": self.bridge, "files": self.files, "prune": []}
        return json.dumps(header).encode() + b"\n" + b"".join(x + (hashlib.sha256(x).digest() if digest else b"0" * 32) for x in data)

    def run_import(self, packet):
        old = os.getcwd()
        try:
            os.chdir(self.project)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.module.run(io.BytesIO(packet), workspace_root=str(self.workspace), temp_root=str(self.temp))
            return json.loads(out.getvalue())
        finally:
            os.chdir(old)

    def test_multiple_regular_files_stream_with_integrity(self):
        result = self.run_import(self.packet())
        self.assertEqual([Path(x).read_bytes() for x in result["paths"]], [b"PDF synthetic", b"print('hi')"])
        self.assertEqual(len(list(self.project.rglob("*"))), 4)

    def test_windows_bind_uid_translation_does_not_require_root_or_chmod(self):
        with patch.object(self.module.os, "getuid", return_value=os.getuid() + 1):
            result = self.run_import(self.packet())
        self.assertEqual(Path(result["paths"][0]).read_bytes(), b"PDF synthetic")

    def test_readonly_uses_private_project_container_tmp_not_shared_identity_home(self):
        result = self.run_import(self.packet(access="ro"))
        self.assertFalse(list(self.project.iterdir()))
        self.assertTrue(all(str(self.temp / ("enge-spx-clipboard-" + self.key)) in path for path in result["paths"]))

    def test_batch_digest_failure_rolls_back_earlier_files_and_temporary_files(self):
        packet = self.packet()
        with self.assertRaises(ValueError):
            self.run_import(packet[:-32] + b"0" * 32)
        self.assertFalse(list((self.project / ".enge-spx-clipboard" / self.bridge).iterdir()))

    def test_truncated_input_fails_without_partial_attachment(self):
        with self.assertRaises(ValueError):
            self.run_import(self.packet()[:-34])
        self.assertFalse(list((self.project / ".enge-spx-clipboard" / self.bridge).iterdir()))

    def test_unique_names_never_overwrite_previous_paste(self):
        packet = self.packet()
        paths = self.run_import(packet)["paths"]
        with self.assertRaises(FileExistsError):
            self.run_import(packet)
        self.assertEqual(Path(paths[0]).read_bytes(), b"PDF synthetic")

    def test_destination_symlinks_cannot_escape_project(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.project / ".enge-spx-clipboard").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.run_import(self.packet())
        self.assertFalse(list(outside.iterdir()))

    def test_quota_rejects_before_creating_files(self):
        self.module.MAX_CACHE = 3
        with self.assertRaisesRegex(ValueError, "cache_limit"):
            self.run_import(self.packet())
        self.assertFalse((self.project / ".enge-spx-clipboard" / self.bridge).exists())

    def test_wrong_project_and_path_traversal_header_rejected(self):
        packet = self.packet()
        header, rest = packet.split(b"\n", 1)
        value = json.loads(header)
        for changed in ({**value, "project": "e" * 16}, {**value, "bridge": "../escape"}, {**value, "files": [{"name": "../evil", "size": 0}]}):
            with self.assertRaises(ValueError):
                self.run_import(json.dumps(changed).encode() + b"\n" + rest)
        self.assertFalse(list(self.project.iterdir()))


class OrderedInputTests(unittest.TestCase):
    def worker(self, transfer=None):
        pty, messages = Mock(), []
        written = []
        pty.write.side_effect = written.append
        ready = threading.Event()
        ready.set()
        worker = OrderedInput(pty, transfer, messages.append, ready)
        self.addCleanup(worker.close)
        return worker, written, messages

    def clipboard(self, snapshot):
        obj = Mock()
        obj.sequence.return_value = 42
        obj.read.return_value = snapshot
        return obj

    def test_mixed_typing_pastes_and_enter_keep_order_and_never_clear(self):
        transfer = Mock(tool="codex")
        transfer.paste.side_effect = lambda item: [text_frame("IMAGE" if item.kind == "image" else "FILE")]
        worker, written, _ = self.worker(transfer)
        worker.put("keys", "请分析：".encode())
        worker.paste(self.clipboard(Snapshot("image", b"fixture")))
        worker.put("keys", " 然后".encode())
        worker.paste(self.clipboard(Snapshot("files", ("fixture.pdf",))))
        worker.put("keys", b"\r")
        wait_for(lambda: len(written) == 5)
        self.assertEqual(written, ["请分析：".encode(), text_frame("IMAGE"), " 然后".encode(), text_frame("FILE"), b"\r"])

    def test_plain_text_never_calls_file_importer(self):
        transfer = Mock()
        worker, written, _ = self.worker(transfer)
        worker.paste(self.clipboard(Snapshot("text", "你好\r\nline 2")))
        wait_for(lambda: bool(written))
        self.assertEqual(written, [text_frame("你好\r\nline 2")])
        transfer.paste.assert_not_called()

    def test_completed_clipboard_snapshot_is_released_while_terminal_is_idle(self):
        import weakref
        class Clipboard:
            def sequence(self):
                return 1
            def read(self, sequence):
                return self.snapshot
        clipboard = Clipboard()
        clipboard.snapshot = Snapshot("text", "transient clipboard")
        reference = weakref.ref(clipboard.snapshot)
        worker, written, _ = self.worker()
        worker.paste(clipboard)
        wait_for(lambda: bool(written))
        clipboard.snapshot = None
        wait_for(lambda: reference() is None)

    def test_disconnected_session_does_not_read_clipboard_or_queue_keys(self):
        worker, written, messages = self.worker()
        worker.close()
        clipboard = self.clipboard(Snapshot("text", "must not be captured"))
        worker.paste(clipboard)
        self.assertFalse(worker.put("keys", b"a"))
        clipboard.sequence.assert_not_called()
        clipboard.read.assert_not_called()
        self.assertFalse(written)
        self.assertTrue(worker.queue.empty())

    def test_failed_file_copy_keeps_draft_and_cancels_queued_enter(self):
        transfer = Mock(tool="claude")
        release = threading.Event()
        def fail(snapshot):
            release.wait(3)
            raise OSError("synthetic-secret-do-not-display")
        transfer.paste.side_effect = fail
        worker, written, messages = self.worker(transfer)
        worker.put("keys", b"draft")
        worker.paste(self.clipboard(Snapshot("files", ("failed",))))
        worker.put("keys", b"suffix")
        worker.put("keys", b"\r")
        release.set()
        wait_for(lambda: any("回车" in x for x in messages))
        self.assertEqual(written, [b"draft", b"suffix"])
        self.assertNotIn("synthetic-secret", "".join(messages))

    def test_parallel_cli_sessions_do_not_share_input_or_clipboard_snapshots(self):
        first, one, _ = self.worker()
        second, two, _ = self.worker()
        first.paste(self.clipboard(Snapshot("text", "project one")))
        second.paste(self.clipboard(Snapshot("text", "project two")))
        wait_for(lambda: bool(one) and bool(two))
        self.assertEqual(one, [text_frame("project one")])
        self.assertEqual(two, [text_frame("project two")])

    def test_no_paste_before_cli_bracketed_input_is_ready(self):
        worker, written, messages = self.worker()
        worker.ready.clear()
        worker.paste(self.clipboard(Snapshot("text", "a\nb")))
        wait_for(lambda: bool(messages))
        self.assertFalse(written)

    def test_empty_and_busy_clipboard_preserve_input(self):
        worker, written, messages = self.worker()
        worker.paste(self.clipboard(Snapshot("empty")))
        busy = self.clipboard(None)
        busy.read.side_effect = SPXError("剪贴板被占用")
        worker.paste(busy)
        wait_for(lambda: len(messages) >= 2)
        self.assertFalse(written)


class TerminalIntegrationTests(unittest.TestCase):
    def test_source_launcher_does_not_import_host_code_from_project(self):
        import subprocess
        from enge_spx.invocation import console_entry, console_environment
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / "must-not-execute"
            (root / "json.py").write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('bad')\nraise RuntimeError('untrusted project imported on host')\n")
            result = subprocess.run([*console_entry(), "--version"], env=console_environment(), cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(sentinel.exists())

    def test_image_acknowledgement_requires_a_new_native_chip(self):
        monitor = ImageAcknowledgement()
        monitor.observe("[Image #1] existing prompt")
        ticket = monitor.ticket()
        monitor.observe("[Image #1] /path/to/image.png")
        self.assertFalse(monitor.wait(ticket, threading.Event(), timeout=.01))
        monitor.observe("[Image #1] text [Image #2]")
        self.assertTrue(monitor.wait(ticket, threading.Event(), timeout=.01))

    def test_keyboard_unicode_arrows_ctrl_and_shift_enter(self):
        def key(code, text="", modifiers=Qt.KeyboardModifier.NoModifier):
            return QKeyEvent(QKeyEvent.Type.KeyPress, code, modifiers, text)
        self.assertEqual(key_bytes(key(Qt.Key.Key_C, modifiers=Qt.KeyboardModifier.ControlModifier)), b"\x03")
        self.assertEqual(key_bytes(key(Qt.Key.Key_Left)), b"\x1b[D")
        self.assertEqual(key_bytes(key(Qt.Key.Key_Up), True), b"\x1bOA")
        self.assertEqual(key_bytes(key(Qt.Key.Key_Return, modifiers=Qt.KeyboardModifier.ShiftModifier)), b"\x1b[13;2u")
        self.assertEqual(key_bytes(key(0, "中文🙂")), "中文🙂".encode())

    def test_terminal_modes_primary_buffer_and_device_query(self):
        responses = []
        screen = TerminalScreen(80, 24, responses.append)
        stream = pyte.Stream(screen)
        stream.feed("draft\x1b[?2004h\x1b[6n")
        self.assertTrue(screen.bracketed)
        self.assertEqual(responses, [b"\x1b[1;6R"])
        stream.feed("\x1b[?1049hOTHER\x1b[?1049l")
        self.assertTrue(screen.display[0].startswith("draft"))
        stream.feed("\x1b[?2004l")
        self.assertFalse(screen.bracketed)

    def test_smart_launcher_gets_public_session_arguments_only(self):
        command = ["spx.exe", "--data", "D:/private", "--project", "D:/项目", "attach", "codex", "--session", "session", "--container", "container"]
        argv, _ = terminal.launch_command({"kind": "smart"}, command, "D:/项目", "title")
        self.assertEqual(argv, [*command, "--smart-terminal"])
        self.assertNotIn("SPX_BROWSER_TOKEN", str(argv))

    def test_transfer_rechecks_container_and_profile_before_pasting(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            engine = Mock(store=Store(base / "private"))
            engine.prefix = "spx-test"
            transfer = Transfer(engine, str(project), "codex", "session", "container")
            transfer.verify()
            engine.attach_command.assert_called_once_with(str(project), "codex", "session", "container", interactive=True)
            transfer.close()
            with self.assertRaises(SPXError):
                transfer.verify()


class CacheLeaseTests(unittest.TestCase):
    def test_active_metadata_can_be_copied_for_existing_storage_migration(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "private")
            plan = {"key": "a" * 16, "profile": "shared", "access": "rw"}
            lease = CacheLease(store, "b" * 32, plan, "container1")
            try:
                target = Path(tmp) / "migrated.json"
                shutil.copy2(lease.path, target)
                self.assertEqual(json.loads(target.read_text()), lease.scope)
                self.assertLess(lease.path.stat().st_size, 1024)
            finally:
                lease.close()

    def test_active_session_is_never_pruned_and_closed_retention_starts_at_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "private")
            plan = {"key": "a" * 16, "profile": "shared", "access": "rw"}
            one = CacheLease(store, "b" * 32, plan, "container1")
            two = CacheLease(store, "c" * 32, plan, "container1")
            try:
                old = time.time() - RETENTION - 100
                os.utime(one.path, (old, old))
                self.assertFalse(two.expired())
                one.close()
                self.assertFalse(two.expired())
                os.utime(one.path, (old, old))
                self.assertEqual(two.expired(), ["b" * 32])
            finally:
                one.close()
                two.close()

    def test_other_project_or_profile_cannot_supply_cleanup_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "private")
            plan = {"key": "a" * 16, "profile": "shared", "access": "ro"}
            one = CacheLease(store, "b" * 32, plan, "container1")
            one.close()
            old = time.time() - RETENTION - 100
            os.utime(one.path, (old, old))
            for changed in ({**plan, "key": "e" * 16}, {**plan, "profile": "d" * 12}):
                two = CacheLease(store, "c" * 32, changed, "container1")
                try:
                    self.assertFalse(two.expired())
                finally:
                    two.close()
                    two.path.unlink()


class NativeWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import queue
        self.output = queue.Queue()
        self.written = []
        self.pty = Mock()
        self.pty.read.side_effect = self.output.get
        self.pty.write.side_effect = self.written.append
        self.pty.close.side_effect = lambda: self.output.put(b"")
        self.clipboard = Mock()
        self.clipboard.sequence.return_value = 1
        self.window = TerminalWindow(self.pty, "codex", Path("project"), clipboard=self.clipboard)
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

    def test_ctrl_v_uses_current_terminal_without_opening_another_window(self):
        from PySide6.QtTest import QTest
        self.clipboard.read.return_value = Snapshot("text", "你好\r\nline two")
        before = set(self.app.topLevelWidgets())
        focused = self.app.focusWidget()
        QTest.keyClick(self.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.pump(lambda: bool(self.written))
        self.assertEqual(self.written, [text_frame("你好\r\nline two")])
        self.assertEqual(set(self.app.topLevelWidgets()), before)
        self.assertIs(self.app.focusWidget(), focused)

    def test_image_ctrl_v_waits_for_the_native_chip_in_this_same_view(self):
        from PySide6.QtTest import QTest
        transfer = Mock(tool="codex")
        transfer.last_images = [True]
        frame = text_frame("/tmp/native-fixture.png")
        transfer.paste.return_value = [frame]
        self.view.sender.transfer = transfer
        self.clipboard.read.return_value = Snapshot("image", png())
        def write(data):
            self.written.append(data)
            if data == frame:
                self.output.put(b"\r\n[Image #1]")
        self.pty.write.side_effect = write
        QTest.keyClick(self.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.pump(lambda: "已交给" in self.window.message.text())
        self.assertEqual(self.written, [frame])
        self.assertNotIn(b"\r", self.written)

    def test_ctrl_c_without_selection_interrupts_and_tab_reaches_cli(self):
        from PySide6.QtTest import QTest
        QTest.keyClick(self.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(self.view, Qt.Key.Key_Tab)
        QTest.keyClick(self.view, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        self.pump(lambda: len(self.written) == 3)
        self.assertEqual(self.written, [b"\x03", b"\t", b"\x1b[Z"])

    def test_wide_unicode_color_and_selection_render_without_corruption(self):
        self.output.put("\x1b[48;2;60;40;30m中文🦄\x1b[0m".encode())
        self.pump(lambda: self.view.screen.buffer[0][0].data == "中")
        self.view.selection = ((0, 0), (0, 5))
        image = self.view.grab().toImage()
        self.assertFalse(image.isNull())


if __name__ == "__main__":
    unittest.main()
