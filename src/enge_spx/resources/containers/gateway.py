"""The proxy loses its outbound route if the host stops renewing its lease."""
import json
from pathlib import Path
import signal
import subprocess
import time


def lease_valid():
    try:
        journal = Path("/config/lease.jsonl")
        with journal.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 4096))
            lines = stream.read().split(b"\n")
        # Ignore an unfinished last line, never a complete revocation record.
        for line in reversed(lines[:-1]):
            if not line.strip():
                continue
            try:
                lease = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            return 0 < float(lease["expires"]) - time.time() <= 310
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    if not lease_valid():
        raise SystemExit("Connection lease is missing or expired.")
    child = subprocess.Popen(["/usr/local/bin/sing-box", "run", "-c", "/config/config.json"])
    stopped = False
    def stop(signum=None, frame=None):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while child.poll() is None and not stopped and lease_valid():
        time.sleep(1)
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    raise SystemExit(child.returncode or 0)


if __name__ == "__main__":
    main()
