"""Private session leases for bounded, inactive-only attachment cache cleanup.

Records contain scope identifiers and timestamps, never clipboard contents or
source paths. A crashed process releases the OS lock automatically.
"""
import json
from itertools import islice
import os
from pathlib import Path
import re
import time

from .state import SPXError

RETENTION = 7 * 24 * 3600


def lock(stream, acquire=True):
    if os.name == "nt":
        # A byte beyond EOF is a valid Windows lock without growing the file.
        # Keep the tiny metadata readable/copyable by data-directory migration.
        stream.seek(1 << 30)
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)


class CacheLease:
    def __init__(self, store, bridge, plan, container):
        self.root = store.home / "clipboard-sessions"
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or getattr(self.root, "is_junction", lambda: False)():
            raise SPXError("附件缓存记录目录包含链接，已拒绝粘贴。")
        self.scope = {"schema": 1, "project": plan["key"], "profile": plan["profile"], "access": plan["access"], "container": container}
        self.path = self.root / (bridge + ".json")
        self.stream = self.path.open("x+b")
        self.stream.write(json.dumps(self.scope).encode("ascii"))
        self.stream.flush()
        lock(self.stream)

    def expired(self):
        cutoff = time.time() - RETENTION
        result = []
        for path in islice(self.root.iterdir(), 4096):
            if len(result) == 64:
                break
            if not re.fullmatch(r"[a-f0-9]{32}\.json", path.name) or path == self.path or path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                continue
            try:
                info = path.stat()
                if info.st_mtime >= cutoff or info.st_size > 1024 or info.st_nlink != 1:
                    continue
                with path.open("r+b") as stream:
                    lock(stream)
                    try:
                        stream.seek(0)
                        value = json.loads(stream.read(1025))
                        expected = self.scope if self.scope["access"] == "ro" else {k: v for k, v in self.scope.items() if k != "container"}
                        if self.scope["access"] == "rw" and isinstance(value, dict):
                            value = {k: v for k, v in value.items() if k != "container"}
                        if value == expected:
                            result.append(path.stem)
                    finally:
                        lock(stream, False)
            except (OSError, ValueError, TypeError):
                continue
        return result

    def forget(self, bridges):
        for bridge in bridges:
            if not re.fullmatch(r"[a-f0-9]{32}", bridge):
                continue
            path = self.root / (bridge + ".json")
            try:
                if path.stat().st_mtime < time.time() - RETENTION:
                    # IDs are generated once and never reused; the expired
                    # session was observed unlocked before this import.
                    path.unlink()
            except OSError:
                pass

    def close(self):
        if self.stream is not None:
            try:
                # Retention starts after the owning terminal closes.
                os.utime(self.path, None)
                lock(self.stream, False)
            finally:
                self.stream.close()
                self.stream = None
