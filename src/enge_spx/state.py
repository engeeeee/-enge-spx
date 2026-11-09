from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
import time

from .brand import DATA_DIRECTORY, LEGACY_DATA_DIRECTORY


class SPXError(RuntimeError):
    pass


def default_home() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
    pointer = location_file()
    if pointer.is_file():
        try:
            value = json.loads(pointer.read_text(encoding="utf-8"))
            target = Path(value["home"])
            if not target.is_absolute():
                raise ValueError()
            target = relocated_home(target)
            identity = json.loads((target / "instance.json").read_text(encoding="utf-8"))
            if not target.is_absolute() or identity["id"] != value["instance"]:
                raise ValueError()
            return target
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SPXError(f"已迁移的数据目录不可用。请连接对应磁盘，或检查位置记录：{pointer}") from error
    current, previous = base / DATA_DIRECTORY, base / LEGACY_DATA_DIRECTORY
    if (current / "relocated.json").is_file():
        return relocated_home(current)
    if not (current / "instance.json").is_file() and (previous / "relocated.json").is_file():
        return relocated_home(previous)
    if not (current / "instance.json").is_file() and (previous / "instance.json").is_file():
        return previous
    return current


def location_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "ENGE-SPX-location.json"


def relocated_home(home: Path) -> Path:
    visited, required = set(), None
    for _ in range(16):
        home = home.expanduser().resolve()
        if home in visited:
            raise SPXError("数据目录的迁移记录存在循环，请检查 relocated.json。")
        visited.add(home)
        marker = home / "relocated.json"
        if not marker.exists():
            if required is not None:
                try:
                    identity = json.loads((home / "instance.json").read_text(encoding="utf-8"))
                    if identity["id"] != required:
                        raise ValueError()
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise SPXError("迁移后的数据目录不可用，请检查磁盘和 relocated.json。") from error
            return home
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            target = Path(value["home"])
            if not target.is_absolute() or not isinstance(value["instance"], str) or required is not None and value["instance"] != required:
                raise ValueError()
            required = value["instance"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SPXError("迁移后的数据目录不可用，请检查磁盘和 relocated.json。") from error
        home = target
    raise SPXError("数据目录的迁移记录过长，请直接选择最新的数据目录。")


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".next-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        # Windows readers (including Docker Desktop's bind-mount bridge) may
        # briefly hold the old file without FILE_SHARE_DELETE. Keep replacement
        # atomic and retry that sharing conflict rather than truncating a lease.
        deadline = time.monotonic() + 3
        delay = .02
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                windows_sharing = getattr(error, "winerror", None) in (5, 32, 33) or os.name == "nt" and error.errno == errno.EACCES
                remaining = deadline - time.monotonic()
                if not windows_sharing or remaining <= 0:
                    raise
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, .2)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Store:
    def __init__(self, home: Path | None = None):
        self.home = relocated_home(home or default_home())
        if any(c in str(self.home) for c in (",", "\n", "\r")):
            raise SPXError("数据目录不能包含逗号或换行。")
        self.home.mkdir(parents=True, exist_ok=True)
        self.instance_file = self.home / "instance.json"
        with self.lock("instance"):
            if not self.instance_file.exists():
                atomic_json(self.instance_file, {"id": uuid.uuid4().hex[:12], "app": "enge-spx", "schema": 1})
        identity = self.read("instance.json")
        self.instance = identity["id"]
        self.legacy = identity.get("app") != "enge-spx"
        if not isinstance(self.instance, str) or len(self.instance) != 12 or any(c not in "0123456789abcdef" for c in self.instance):
            raise SPXError("数据目录的安装标识无效，请使用其他专用目录。")

    def read(self, name: str, default=None):
        path = self.home / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise SPXError(f"无法读取 {name}；请保留数据目录并检查文件。") from error

    def write(self, name: str, value) -> None:
        self.check_location()
        atomic_json(self.home / name, value)

    def check_location(self):
        if (self.home / "relocated.json").exists():
            raise SPXError("数据已迁移，请重新打开 ENGE SPX 后继续。")

    def settings(self) -> dict:
        # Older versions enabled Desktop startup when opening the GUI. Keep the
        # legacy field false even for those settings; startup now requires a click.
        return {"context": "desktop-linux", "timezone": "America/Los_Angeles", "selected": "", "projects": [], "terminal": {"kind": "auto"}, "relay": {"enabled": False, "downloads": True}, **self.read("settings.json", {}), "auto_start_docker": False}

    @contextmanager
    def lock(self, name="operation", timeout=0, on_wait=None):
        self.check_location()
        path = self.home / (name + ".lock")
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            deadline = time.monotonic() + timeout
            waiting = False
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SPXError("环境正在执行其他操作，请稍后重试。") from error
                    if not waiting and on_wait:
                        on_wait()
                    waiting = True
                    time.sleep(min(.1, remaining))
            try:
                self.check_location()
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def project(self, path: str) -> tuple[Path, str]:
        directory = Path(path).expanduser().resolve(strict=True)
        if not directory.is_dir() or directory == directory.parent or directory == Path.home().resolve():
            raise SPXError("请选择具体项目文件夹，不要共享整块磁盘或用户主目录。")
        if directory == self.home or self.home in directory.parents or directory in self.home.parents:
            raise SPXError("项目目录不能包含应用数据目录，也不能位于应用数据目录中。")
        if "," in str(directory) or "\n" in str(directory) or "\r" in str(directory):
            raise SPXError("此版本不支持路径中包含逗号或换行的项目。")
        identity = hashlib.sha256(os.path.normcase(str(directory)).encode()).hexdigest()[:16]
        return directory, identity


def status_snapshot(store):
    state = store.read("runtime.json", {"phase": "stopped"})
    return {"phase": state["phase"], "reason": state.get("reason", ""), "evidence": state.get("evidence"), "checked": state.get("checked"), "confirmed": state.get("confirmed"), "guard_age": round(time.time() - state.get("heartbeat", time.time())), "timezone": store.settings()["timezone"]}
