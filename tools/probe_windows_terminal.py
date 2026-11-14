"""Owned Windows console probe using synthetic input, never personal clipboard."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from enge_spx.terminal_pty import WindowsPTY


def main():
    if os.name != "nt":
        raise SystemExit("Windows probe only")
    child = r'''import ctypes,sys
k=ctypes.WinDLL('kernel32');k.SetConsoleCP(65001);k.SetConsoleOutputCP(65001)
k.GetStdHandle.argtypes=[ctypes.c_ulong];k.GetStdHandle.restype=ctypes.c_void_p
k.GetConsoleMode.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
k.SetConsoleMode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
mode=ctypes.c_ulong();handle=k.GetStdHandle(0xfffffff6);k.GetConsoleMode(handle,ctypes.byref(mode))
# The documented moby/term raw flags used by the Windows Docker client.
raw=(mode.value & ~(1|2|4|8|16))|0x80|0x20|0x40|0x200
if not k.SetConsoleMode(handle,raw):raise OSError('raw input unavailable')
k.SetConsoleMode(k.GetStdHandle(0xfffffff5),7)
sys.stdout.write('\x1b[?1000h\x1b[?1002h\x1b[?1006hSPX_MOUSE_READY');sys.stdout.flush()
data=bytearray()
while len(data)<4096:
 b=sys.stdin.buffer.read(1)
 if not b:break
 data.extend(b)
 if b==b'\x16':break
sys.stdout.write('SPX_MOUSE_BYTES:'+data.hex());sys.stdout.flush()
'''
    with tempfile.TemporaryDirectory() as folder:
        pty = WindowsPTY([sys.executable, "-u", "-c", child], dict(os.environ), folder)
        output = bytearray()
        def read():
            while block := pty.read():
                output.extend(block)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 12
            while b"SPX_MOUSE_READY" not in output and time.monotonic() < deadline:
                time.sleep(.01)
            if b"SPX_MOUSE_READY" not in output:
                raise AssertionError("Owned probe did not become ready")
            expected = b"\x1b[<0;12;8M\x1b[<0;12;8m\x16"
            pty.write(expected)
            while b"SPX_MOUSE_BYTES:" not in output and time.monotonic() < deadline:
                time.sleep(.01)
            while pty.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            reader.join(1)
            marker = bytes(output).partition(b"SPX_MOUSE_BYTES:")[2]
            end = 0
            while end < len(marker) and marker[end:end+1] in b"0123456789abcdef":
                end += 1
            received = bytes.fromhex(marker[:end].decode()) if end else b""
            report = {"scope": "Owned real ConPTY, Docker-style Windows raw console flags, synthetic SGR input",
                      "ready": True, "input_exact": received == expected,
                      "input_hex": received.hex(), "expected_hex": expected.hex(),
                      "mouse_1000_forwarded": b"\x1b[?1000h" in output,
                      "mouse_1006_forwarded": b"\x1b[?1006h" in output}
            print(json.dumps(report), flush=True)
            destination = os.environ.get("SPX_TERMINAL_PROBE_REPORT")
            if destination:
                Path(destination).write_text(json.dumps(report, indent=2), encoding="utf-8")
        finally:
            pty.close()
            reader.join(3)


if __name__ == "__main__":
    main()
