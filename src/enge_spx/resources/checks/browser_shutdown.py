"""Bounded graceful exit of the verified browser main process, never PID 1.

Injected through Docker exec into an already owned browser container. Chromium
handles SIGINT as a normal user exit, allowing pending Profile data to flush.
No debug port, account reads, capabilities, image changes or host process signals.
"""
import json
import os
from pathlib import Path
import signal
import time


def main_process(root, pid):
    if type(pid) is not int or pid <= 1:
        return False
    directory = root / str(pid)
    if directory.stat().st_uid != os.getuid():
        return False
    arguments = (directory / "cmdline").read_bytes().split(b"\0")
    return (Path(os.fsdecode(arguments[0])).name == "chromium"
            and not any(value.startswith(b"--type=") for value in arguments)
            and not any(value in arguments for value in (b"--new-tab", b"--headless", b"--no-sandbox"))
            and b"--user-data-dir=/home/workspace/.config/chromium-spx" in arguments)


def close(status=Path("/tmp/spx-sandbox-status.json"), root=Path("/proc")):
    requested = False
    try:
        with status.open(encoding="utf-8") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return {"requested": False, "exited": False}
        record = json.loads(raw)
        renderer = record["renderer"]
        if type(record.get("schema")) is not int or record["schema"] != 1 or not all(renderer.get(key) is True for key in ("non_root", "no_new_privileges", "no_capabilities", "seccomp", "additional_seccomp_filter", "nested_pid_namespace")):
            return {"requested": False, "exited": False}
        candidates = []
        # Released sandbox reports contain verified flags, not a live browser PID.
        # Find exactly one current main process; never signal renderer/probe/IPC
        # launch processes or guess when multiple candidates remain.
        for directory in root.iterdir():
            if directory.name.isdecimal():
                try:
                    if main_process(root, int(directory.name)):
                        candidates.append(int(directory.name))
                except OSError:
                    continue
        if len(candidates) != 1:
            return {"requested": False, "exited": False}
        pid = candidates[0]
        os.kill(pid, signal.SIGINT)
        requested = True
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                if not main_process(root, pid):
                    return {"requested": True, "exited": True}
            except FileNotFoundError:
                return {"requested": True, "exited": True}
            time.sleep(.05)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        pass
    return {"requested": requested, "exited": False}


if __name__ == "__main__":
    print(json.dumps(close()))
