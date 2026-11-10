"""One bounded stdin transfer into container-local RAM; print no input data."""
import json
import os
from pathlib import Path
import re
import stat
import sys

LIMIT = 1024 * 1024


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Unsafe runtime directory")
    path.parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())


def main():
    try:
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if not raw or len(raw) > LIMIT or len(sys.argv) != 2:
            raise ValueError()
        value = json.loads(raw)
        if sys.argv[1] == "gateway" and isinstance(value.get("outbounds"), list):
            write_private("/tmp/spx/config.json", value)
        elif sys.argv[1] == "browser" and re.fullmatch("[a-f0-9]{64}", value.get("token", "")) and str(value.get("proxy", "")).startswith("http://"):
            write_private("/dev/shm/spx/browser.json", value)
        else:
            raise ValueError()
        print("ready")
    except Exception:
        raise SystemExit("Runtime credential transfer rejected; input omitted.")


if __name__ == "__main__":
    main()
