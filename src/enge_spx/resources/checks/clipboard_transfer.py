"""Fixed, unprivileged Docker stdin importer. No shell, socket or new mounts.

Protocol: one bounded JSON line; exact file bytes then 32-byte SHA256 per file.
All destination operations are relative to held O_NOFOLLOW directory handles.
"""
import hashlib
import ctypes
import errno
import json
import os
import re
import stat
import sys
import time

MAX_FILE = 128 * 1024 * 1024
MAX_BATCH = 256 * 1024 * 1024
MAX_CACHE = 1024 * 1024 * 1024
MAX_ENTRIES = 8192
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def directory(parent, name, *, enforce_owner=True):
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    result = os.open(name, FLAGS, dir_fd=parent)
    info = os.fstat(result)
    # Windows bind files can report a synthetic/root UID despite the selected
    # non-root user having host-ACL-authorized access. Private /tmp requires
    # ownership; an exact audited project bind uses descriptor/path protection.
    if enforce_owner and info.st_uid != os.getuid():
        os.close(result)
        raise ValueError("directory_owner")
    return result


def usage(root):
    count, total = 0, 0
    for bridge in os.listdir(root):
        if not re.fullmatch(r"[a-f0-9]{32}", bridge):
            raise ValueError("cache_entry")
        child = os.open(bridge, FLAGS, dir_fd=root)
        try:
            for name in os.listdir(child):
                info = os.stat(name, dir_fd=child, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("cache_entry")
                count += 1
                total += info.st_size
                if count > MAX_ENTRIES or total > MAX_CACHE:
                    raise ValueError("cache_limit")
        finally:
            os.close(child)
    return total, count


def exact(stream, n):
    chunks = bytearray()
    while len(chunks) < n:
        data = stream.read(min(n - len(chunks), 1024 * 1024))
        if not data:
            raise ValueError("short_input")
        chunks.extend(data)
    return bytes(chunks)


def commit(directory_fd, temporary, name):
    # Prefer atomic no-replace rename, including filesystems without hardlinks.
    # Fall back only to another atomic no-overwrite operation, never replace().
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    if rename is not None:
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(directory_fd, os.fsencode(temporary), directory_fd, os.fsencode(name), 1) == 0:
            return
        code = ctypes.get_errno()
        if code not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise OSError(code, "attachment_commit")
    os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
    os.unlink(temporary, dir_fd=directory_fd)


def prune(root, bridges, *, enforce_owner=True):
    cutoff = time.time() - 7 * 24 * 3600
    removed = []
    for bridge in bridges:
        try:
            child = os.open(bridge, FLAGS, dir_fd=root)
        except FileNotFoundError:
            removed.append(bridge)
            continue
        try:
            info = os.fstat(child)
            if (enforce_owner and info.st_uid != os.getuid()) or info.st_mtime >= cutoff:
                continue
            names = os.listdir(child)
            if len(names) > MAX_ENTRIES:
                continue
            valid = True
            for name in names:
                info = os.stat(name, dir_fd=child, follow_symlinks=False)
                if not re.fullmatch(r"(?:\.next-)?[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?", name) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mtime >= cutoff:
                    valid = False
                    break
            if valid:
                for name in names:
                    os.unlink(name, dir_fd=child)
                os.rmdir(bridge, dir_fd=root)
                removed.append(bridge)
        finally:
            os.close(child)
    return removed


def run(stream, *, workspace_root="/workspace", temp_root="/tmp"):
    line = stream.readline(16385)
    if len(line) > 16384 or not line.endswith(b"\n"):
        raise ValueError("header")
    header = json.loads(line)
    if set(header) != {"schema", "project", "access", "bridge", "files", "prune"} or type(header["schema"]) is not int or header["schema"] != 1:
        raise ValueError("header")
    key, bridge, access, files = (header[x] for x in ("project", "bridge", "access", "files"))
    if not re.fullmatch(r"[a-f0-9]{16}", key) or not re.fullmatch(r"[a-f0-9]{32}", bridge) or access not in ("rw", "ro"):
        raise ValueError("scope")
    old = header["prune"]
    if not isinstance(old, list) or len(old) > 64 or any(not isinstance(x, str) or not re.fullmatch(r"[a-f0-9]{32}", x) or x == bridge for x in old):
        raise ValueError("prune")
    project = workspace_root + "/" + key
    if os.getcwd() != project or not isinstance(files, list) or not 1 <= len(files) <= 32:
        raise ValueError("scope")
    names, total = set(), 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"name", "size"} or not isinstance(item["name"], str) or not re.fullmatch(r"[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?", item["name"]):
            raise ValueError("file")
        if type(item["size"]) is not int or not 0 <= item["size"] <= MAX_FILE or item["name"] in names:
            raise ValueError("file")
        names.add(item["name"])
        total += item["size"]
    if total > MAX_BATCH:
        raise ValueError("batch_limit")
    # /tmp is already private to this project container. Never use the shared
    # identity home as a read-only project's transfer destination.
    base = project if access == "rw" else temp_root
    root_name = ".enge-spx-clipboard" if access == "rw" else "enge-spx-clipboard-" + key
    anchor = os.open(base, FLAGS)
    root = target = None
    created = []
    try:
        root = directory(anchor, root_name, enforce_owner=access == "ro")
        # Serialize quota checking and commit across concurrent terminal sessions.
        import fcntl
        fcntl.flock(root, fcntl.LOCK_EX)
        removed = prune(root, old, enforce_owner=access == "ro")
        used, count = usage(root)
        if used + total > MAX_CACHE or count + len(files) > MAX_ENTRIES:
            raise ValueError("cache_limit")
        target = directory(root, bridge, enforce_owner=access == "ro")
        for item in files:
            name, size = item["name"], item["size"]
            temporary = ".next-" + name
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=target)
            created.append(temporary)
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as out:
                left = size
                while left:
                    data = exact(stream, min(left, 1024 * 1024))
                    out.write(data)
                    digest.update(data)
                    left -= len(data)
                out.flush()
                os.fsync(out.fileno())
            if exact(stream, 32) != digest.digest():
                raise ValueError("digest")
            commit(target, temporary, name)
            created.append(name)
            created.remove(temporary)
        prefix = base + "/" + root_name + "/" + bridge + "/"
        print(json.dumps({"schema": 1, "paths": [prefix + item["name"] for item in files], "pruned": removed}), flush=True)
    except BaseException:
        if target is not None:
            for name in created:
                try:
                    os.unlink(name, dir_fd=target)
                except OSError:
                    pass
        raise
    finally:
        for fd in (target, root, anchor):
            if fd is not None:
                os.close(fd)


if __name__ == "__main__":
    try:
        run(sys.stdin.buffer)
    except (ValueError, TypeError, KeyError, OSError, EOFError):
        # A fixed error only. Never echo imported contents or host/source paths.
        print('{"error":"clipboard_import_failed"}', file=sys.stderr)
        sys.exit(2)
