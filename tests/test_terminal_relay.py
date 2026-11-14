"""Actual pipe/PTY transport tests; synthetic input, no accounts or clipboard."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.terminal_pty import DockerPTY
from enge_spx.state import SPXError

RELAY = (PACKAGE_RESOURCES / "checks/terminal_relay.py").read_text(encoding="utf-8")


class TransportHarness:
    def open(self, command, env=None):
        pty = DockerPTY(command, dict(os.environ) if env is None else env, tempfile.gettempdir())
        self.addCleanup(pty.close)
        self.blocks, self.received = queue.Queue(), bytearray()
        def drain():
            while block := pty.read():
                self.blocks.put(block)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        return pty

    def wait(self, token, seconds=5):
        deadline = time.monotonic() + seconds
        while token not in self.received:
            left = deadline - time.monotonic()
            if left <= 0:
                self.fail("Owned transport did not deliver the synthetic marker")
            try:
                self.received.extend(self.blocks.get(timeout=left))
            except queue.Empty:
                self.fail("Owned transport timed out")
        return bytes(self.received)


class PipeTests(TransportHarness, unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Actual Docker CLI required; no daemon is used")
    def test_actual_docker_cli_hijack_preserves_raw_mouse_and_draft_bytes(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def answer(self, value):
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Api-Version", "1.47")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            def do_HEAD(self):
                self.answer("OK")
            def do_GET(self):
                self.answer({"Running": False, "ExitCode": 0} if "/exec/" in self.path else {"ApiVersion": "1.47", "Version": "fixture"})
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                value = json.loads(body or b"{}")
                if self.path.endswith("/exec"):
                    self.server.tty = value.get("Tty")
                    return self.answer({"Id": "owned-fixture-exec"})
                if not self.path.endswith("/start"):
                    return self.answer({})
                self.connection.settimeout(5)
                self.send_response(101)
                self.send_header("Connection", "Upgrade")
                self.send_header("Upgrade", "tcp")
                self.send_header("Content-Type", "application/vnd.docker.raw-stream")
                self.end_headers()
                self.wfile.flush()
                def frame():
                    kind, size = struct.unpack("!cI", self.rfile.read(5))
                    assert size <= 65536
                    return kind, self.rfile.read(size)
                def output(data):
                    self.wfile.write(struct.pack("!BxxxI", 1, len(data)) + data)
                    self.wfile.flush()
                kind, data = frame()
                assert kind == b"R" and data == struct.pack("!HH", 110, 32)
                output(b"\x1b[?1000h\x1b[?1006hREADY")
                kind, data = frame()
                assert kind == b"D"
                output(b"RESULT:" + data.hex().encode() + b"END")
                self.close_connection = True
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as folder:
            command = [shutil.which("docker"), "--config", folder, "--host", "tcp://127.0.0.1:" + str(server.server_port),
                       "exec", "-i", "owned-fixture-container", "synthetic-no-op"]
            # Do not read or alter any user's Docker context, auth or TLS config.
            allowed = {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TMP", "TEMP", "HOME"}
            environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
            environment.update(DOCKER_API_VERSION="1.47", NO_PROXY="127.0.0.1,localhost")
            pty = self.open(command, environment)
            self.wait(b"READY")
            self.assertFalse(server.tty)
            data = "\x1b[<0;21;9M\x1b[<0;21;9m\x1b[200~中文\n\n\x1b[201~".encode()
            pty.write(data)
            self.assertIn(b"RESULT:" + data.hex().encode(), self.wait(b"END"))
            pty.close()

    def test_host_pipes_preserve_mouse_modes_unicode_and_paste_without_console(self):
        # Runs on real Windows as well: no ConPTY/console API interprets modes.
        code = '''import sys,struct,os
assert not os.isatty(0)
def frame():
 h=sys.stdin.buffer.read(5);k,n=struct.unpack('!cI',h)
 return k,sys.stdin.buffer.read(n)
k,d=frame();assert k==b'R' and d==struct.pack('!HH',110,32)
sys.stdout.buffer.write(b'\\x1b[?1000h\\x1b[?1006hREADY');sys.stdout.buffer.flush()
k,d=frame();assert k==b'D'
sys.stdout.buffer.write(b'RESULT:'+d.hex().encode()+b'END');sys.stdout.buffer.flush()
'''
        pty = self.open([sys.executable, "-u", "-c", code])
        self.wait(b"READY")
        data = "\x1b[<0;300;45M\x1b[<0;300;45m\x1b[200~中文🙂\ntext\x1b[201~".encode()
        pty.write(data)
        actual = self.wait(b"END")
        self.assertIn(b"\x1b[?1000h\x1b[?1006h", actual)
        self.assertIn(b"RESULT:" + data.hex().encode() + b"END", actual)
        pty.close()
        with self.assertRaises(SPXError):
            pty.write(b"late")

    def test_grid_bounds_reject_invalid_sizes(self):
        pty = self.open([sys.executable, "-u", "-c", "import time;print('READY',flush=True);time.sleep(10)"])
        self.wait(b"READY")
        for columns, rows in ((0, 20), (80, 1001), (-1, 3)):
            with self.assertRaises(SPXError):
                pty.resize(columns, rows)

    def test_close_unblocks_a_stalled_writer_and_only_stops_owned_process(self):
        pty = self.open([sys.executable, "-u", "-c", "import time;print('READY',flush=True);time.sleep(30)"])
        self.wait(b"READY")
        stopped = threading.Event()
        def write():
            try:
                pty.write(b"x" * 1_000_000)
            except SPXError:
                pass
            finally:
                stopped.set()
        thread = threading.Thread(target=write, daemon=True)
        thread.start()
        time.sleep(.05)
        begin = time.monotonic()
        pty.close()
        self.assertTrue(stopped.wait(3))
        self.assertLess(time.monotonic() - begin, 5)
        self.assertIsNotNone(pty.poll())


@unittest.skipIf(os.name == "nt", "Linux PTY lives inside the existing container")
class LinuxRelayTests(TransportHarness, unittest.TestCase):
    def relay(self, script):
        return self.open([sys.executable, "-I", "-c", RELAY, "110", "32", sys.executable, "-u", "-c", script])

    def test_linux_pty_mouse_bytes_tty_unicode_and_resize_reach_same_child(self):
        script = '''import os,sys,tty,signal,json
assert os.isatty(0) and os.isatty(1)
assert os.tcgetpgrp(0)==os.getpgrp()
tty.setraw(0)
def size(*args):
 s=os.get_terminal_size(0);os.write(1,('SIZE:%d,%d!'%(s.columns,s.lines)).encode())
signal.signal(signal.SIGWINCH,size)
os.write(1,b'\\x1b[?1000h\\x1b[?1002h\\x1b[?1006hREADY')
data=bytearray()
while not data.endswith(b'\\x16'):
 data.extend(os.read(0,4096))
os.write(1,b'RESULT:'+data.hex().encode()+b'END')
'''
        pty = self.relay(script)
        self.wait(b"READY")
        pty.resize(151, 41)
        self.wait(b"SIZE:151,41!")
        data = "\x1b[<0;12;8M\x1b[<0;12;8m中文🙂\x1b[200~line\nsecond\x1b[201~\x16".encode()
        pty.write(data)
        self.assertIn(b"RESULT:" + data.hex().encode() + b"END", self.wait(b"END"))

    def test_disconnect_hangs_up_owned_cli_and_leaves_another_session_alive(self):
        other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"])
        self.addCleanup(lambda: (other.terminate(), other.wait(timeout=3)))
        pty = self.relay("import os,time;print('CHILD:%d!'%os.getpid(),flush=True);time.sleep(30)")
        data = self.wait(b"!")
        pid = int(data.split(b"CHILD:")[1].split(b"!")[0])
        pty.close()
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertIsNone(other.poll())

    def test_invalid_frame_is_bounded_and_closes_pty(self):
        process = subprocess.Popen([sys.executable, "-I", "-c", RELAY, "80", "24", sys.executable, "-c", "import time;time.sleep(30)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate(struct.pack("!cI", b"D", 65537), timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertFalse(error)

    def test_payload_larger_than_single_frame_is_preserved(self):
        pty = self.relay("import tty,os,hashlib;tty.setraw(0);os.write(1,b'READY');d=bytearray()\nwhile len(d)<90000:d.extend(os.read(0,16384))\nos.write(1,b'HASH:'+hashlib.sha256(d).hexdigest().encode()+b'END')")
        self.wait(b"READY")
        data = b"x" * 90000
        pty.write(data)
        import hashlib
        self.assertIn(b"HASH:" + hashlib.sha256(data).hexdigest().encode(), self.wait(b"END"))
