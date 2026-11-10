"""The proxy loses its outbound route if the host stops renewing its lease."""
import json
import os
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
    import fcntl
    if not lease_valid():
        raise SystemExit("Connection lease is missing or expired.")
    # Credentials arrive on exec stdin after container creation. They are never
    # part of an image, container argv/environment or a host plaintext bind mount.
    config = Path("/tmp/spx/config.json")
    deadline = time.monotonic() + 30
    while not config.is_file():
        if time.monotonic() >= deadline or not lease_valid():
            raise SystemExit("Runtime configuration was not delivered.")
        time.sleep(.05)
    data = config.read_bytes()
    config.unlink()
    if not data or len(data) > 1024 * 1024:
        raise SystemExit("Runtime configuration rejected.")
    descriptor = os.memfd_create("spx-config", os.MFD_ALLOW_SEALING)
    with os.fdopen(os.dup(descriptor), "wb") as output:
        output.write(data)
    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
    child = subprocess.Popen(["/usr/local/bin/sing-box", "run", "-c", f"/proc/self/fd/{descriptor}"], pass_fds=(descriptor,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(descriptor)
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
