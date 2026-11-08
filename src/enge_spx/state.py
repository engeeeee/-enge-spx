from __future__ import annotations

from contextlib import contextmanager
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
    current, previous = base / DATA_DIRECTORY, base / LEGACY_DATA_DIRECTORY
    if not (current / "instance.json").is_file() and (previous / "instance.json").is_file():
        return previous
    return current


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".next-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Store:
    def __init__(self, home: Path | None = None):
        self.home = (home or default_home()).expanduser().resolve()
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
        atomic_json(self.home / name, value)

    def settings(self) -> dict:
        return {"context": "desktop-linux", "timezone": "America/Los_Angeles", "selected": "", "projects": [], "relay": {"enabled": False, "downloads": True}, **self.read("settings.json", {})}

    @contextmanager
    def lock(self, name="operation"):
        path = self.home / (name + ".lock")
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise SPXError("环境正在执行其他操作，请稍后重试。") from error
            try:
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
