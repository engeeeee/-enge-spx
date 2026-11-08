"""The proxy loses its outbound route if the host stops renewing its lease."""
import json
from pathlib import Path
import signal
import subprocess
import time


def lease_valid():
    try:
        lease = json.loads(Path("/config/lease.json").read_text())
        return 0 < float(lease["expires"]) - time.time() <= 310
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
