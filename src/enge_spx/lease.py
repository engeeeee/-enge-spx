"""Append complete lease records without replacing a Docker-mounted file."""
import json
import os


def write_lease(store, expires, reset=False):
    store.check_location()
    path = store.home / "gateway/lease.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # One writer holds the operation lock. Readers use only the final complete
    # line; a partial write cannot extend the previous successful lease.
    record = ("\n" + json.dumps({"expires": expires}, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0) | (os.O_TRUNC if reset else os.O_APPEND)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(record)
        stream.flush()
        os.fsync(stream.fileno())
