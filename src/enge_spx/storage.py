"""Verified app-data relocation and a Docker Desktop disk-move assistant.

Docker owns its VHDX migration. We only read Desktop's settings and verify the
result; no unregister, prune, VHDX edits, or writes to Docker's settings file.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from .state import SPXError, Store, atomic_json, location_file

DOCKER_STORAGE_DOC = "https://docs.docker.com/desktop/features/wsl/#turn-on-docker-desktop-wsl-2"
TRANSIENT = {"relay.json", "forward.json", "ui-smoke.json"}
LOCK_FILES = {name + ".lock" for name in ("operation", "instance", "guard", "forward", "relay")}


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _files(home: Path):
    for parent, directories, files in os.walk(home, followlinks=False):
        for name in [*directories, *files]:
            if _linked(Path(parent) / name):
                raise SPXError("数据目录包含符号链接或目录联接，请先处理这些链接再迁移。")
        for name in files:
            path = Path(parent) / name
            relative = path.relative_to(home)
            if relative.as_posix() in LOCK_FILES | TRANSIENT:
                continue
            if not path.is_file():
                raise SPXError("数据目录包含无法迁移的特殊文件。")
            yield relative, path.stat()


def destination_path(value: str | Path, forbidden=()) -> Path:
    if not str(value).strip():
        raise SPXError("请选择迁移目标文件夹。")
    path = Path(os.path.expandvars(str(value))).expanduser()
    if not path.is_absolute():
        raise SPXError("迁移目标必须是完整路径，例如 D:\\ENGE-SPX\\data。")
    if any(c in str(path) for c in (",", "\n", "\r", "\0")):
        raise SPXError("目标路径不能包含逗号、换行或空字符。")
    for part in (path, *path.parents):
        if _linked(part):
            raise SPXError("迁移目标不能经过符号链接或目录联接。")
    path = path.resolve()
    if path == path.parent or path == Path.home().resolve():
        raise SPXError("请选择专用的空文件夹，不能选择整块磁盘或用户主目录。")
    for item in forbidden:
        other = Path(item).resolve()
        if path == other or path in other.parents or other in path.parents:
            raise SPXError("迁移目标不能与原数据目录、项目目录或另一类数据目录重叠。")
    if path.exists() and (not path.is_dir() or next(path.iterdir(), None) is not None):
        raise SPXError("迁移目标必须是空文件夹；已有数据不会被覆盖。")
    return path


def _parent(path: Path) -> Path:
    parent = path.parent
    while not parent.exists():
        if parent == parent.parent:
            raise SPXError("目标磁盘尚未连接或路径不可用，请先连接磁盘再迁移。")
        parent = parent.parent
    if not parent.is_dir():
        raise SPXError("迁移目标的父路径不是文件夹。")
    return parent


def _private_directory(path: Path):
    if os.name != "nt":
        path.chmod(0o700)
        return
    # The new drive may grant other local accounts read access by inheritance.
    # Protect proxy credentials before writing any data, using language-neutral SIDs.
    import re
    system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        identity = subprocess.run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"], capture_output=True, timeout=10, creationflags=flags, check=True)
        match = re.search(rb'"(S-1-\d+(?:-\d+)+)"\s*$', identity.stdout)
        if not match:
            raise ValueError()
        sid = match.group(1).decode("ascii")
        subprocess.run([str(system / "icacls.exe"), str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"], capture_output=True, timeout=15, creationflags=flags, check=True)
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError) as error:
        raise SPXError("无法设置目标文件夹的个人访问权限，迁移未开始。请选择支持 Windows 文件权限的本地磁盘目录。") from error


def plan_migration(store: Store, value: str | Path) -> dict:
    forbidden = [store.home, *store.settings()["projects"]]
    desktop = desktop_storage()
    if desktop["configured"]:
        forbidden.append(desktop["folder"])
    target = destination_path(value, forbidden)
    files = list(_files(store.home))
    total = sum(stat.st_size for _, stat in files)
    free = shutil.disk_usage(_parent(target)).free
    if free < total + 64 * 1024**2:
        raise SPXError("目标磁盘空间不足，请预留数据大小及至少 64 MB 的额外空间。")
    return {"source": str(store.home), "target": str(target), "bytes": total, "files": len(files), "free": free}


def migrate_home(store: Store, value: str | Path, stop, progress=lambda value: None, wait_seconds=45) -> dict:
    """Keep the source usable until a verified destination is committed.

    Caller supplies the stop operation; the operation and all background locks
    stay held through copying and activation. A tiny redirect remains at the old
    path so existing --data shortcuts cannot create a second installation.
    """
    plan = plan_migration(store, value)
    source, target = store.home, Path(plan["target"])
    stage = target.with_name("." + target.name + ".spx-moving-" + uuid.uuid4().hex[:10])
    committed, fingerprints, leftovers = False, {}, []
    with store.lock():
        progress({"stage": "stop", "message": "停止工作区，等待后台监测和显示服务退出…"})
        stop()
        with ExitStack() as locks:
            deadline = time.monotonic() + wait_seconds
            for name in ("guard", "forward", "relay"):
                while True:
                    try:
                        locks.enter_context(store.lock(name))
                        break
                    except SPXError:
                        if time.monotonic() >= deadline:
                            raise SPXError("后台服务尚未退出，迁移未开始。请稍后重试，原数据仍在原位。")
                        time.sleep(.2)
            # Stopping can write runtime/lease files; calculate the final plan now.
            plan = plan_migration(store, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.mkdir(mode=0o700)
            try:
                _private_directory(stage)
                files = list(_files(source))
                copied, last_report = 0, 0.0
                for relative, before in files:
                    old, new = source / relative, stage / relative
                    new.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with old.open("rb") as incoming, new.open("xb") as outgoing:
                        while chunk := incoming.read(1024 * 1024):
                            outgoing.write(chunk)
                            digest.update(chunk)
                            copied += len(chunk)
                            if time.monotonic() - last_report > .15:
                                progress({"stage": "copy", "bytes": copied, "total": plan["bytes"], "message": "复制并校验应用数据…"})
                                last_report = time.monotonic()
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    shutil.copystat(old, new)
                    after = old.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or _digest(new) != digest.hexdigest():
                        raise SPXError("迁移期间源文件发生变化或复制校验失败。原数据已保留，请重试。")
                    fingerprints[relative] = digest.hexdigest()
                identity = json.loads((stage / "instance.json").read_text(encoding="utf-8"))
                if identity["id"] != store.instance:
                    raise SPXError("安装标识校验失败，已中止迁移。")
                progress({"stage": "activate", "message": "数据校验通过，正在切换默认位置…"})
                # Refuse a destination that changed since preflight.
                destination_path(target, [source, *store.settings()["projects"]])
                if target.exists():
                    target.rmdir()
                stage.rename(target)
                receipt = {"schema": 1, "home": str(target), "instance": store.instance, "source": str(source), "migrated": time.time(), "bytes": plan["bytes"]}
                atomic_json(target / "storage-migration.json", receipt)
                # Source redirect first: even a crash before the default pointer
                # update follows the complete destination on the next start.
                atomic_json(source / "relocated.json", receipt)
                committed = True
                try:
                    atomic_json(location_file(), {"schema": 1, "home": str(target), "instance": store.instance})
                except OSError:
                    leftovers.append("默认位置记录写入失败；旧目录的迁移记录仍可找到新数据。")
                progress({"stage": "cleanup", "message": "释放原目录中已校验的数据和缓存…"})
                for relative, digest in fingerprints.items():
                    old = source / relative
                    try:
                        if _digest(old) != digest:
                            leftovers.append(str(old))
                        else:
                            old.unlink()
                    except OSError:
                        leftovers.append(str(old))
                for relative in TRANSIENT:
                    try:
                        (source / relative).unlink(missing_ok=True)
                    except OSError:
                        leftovers.append(str(source / relative))
                for parent, _, _ in os.walk(source, topdown=False):
                    if Path(parent) != source:
                        try:
                            Path(parent).rmdir()
                        except OSError:
                            pass
                receipt["leftovers"] = leftovers
                atomic_json(target / "storage-migration.json", receipt)
            except Exception as error:
                if not committed:
                    shutil.rmtree(stage, ignore_errors=True)
                    # A complete renamed copy can remain if writing the source
                    # redirect failed. Never delete it or activate it implicitly.
                    raise SPXError(f"应用数据迁移未完成，原数据仍在 {source}。请检查目标目录后重试。原因：{error}") from error
                # After activation, always return the new home to the UI, even if
                # deleting an old locked log or writing the cleanup receipt fails.
                leftovers.append("迁移已完成，原目录部分文件未能清理。")
    progress({"stage": "done", "message": "应用数据已迁移；重新检查连接后即可继续工作。"})
    return {**plan, "leftovers": leftovers}


def _vhdx_files(folder: Path) -> list[dict]:
    result = []
    if not folder.is_dir():
        return result
    for parent, directories, files in os.walk(folder, followlinks=False):
        depth = len(Path(parent).relative_to(folder).parts)
        directories[:] = [name for name in directories if depth < 3 and not _linked(Path(parent) / name)]
        for name in files:
            path = Path(parent) / name
            if path.suffix.lower() == ".vhdx" and not _linked(path):
                try:
                    result.append({"path": str(path), "bytes": path.stat().st_size, "allocated": _allocated_size(path)})
                except OSError:
                    pass
    return result


def _allocated_size(path: Path) -> int:
    stat = path.stat()
    if os.name != "nt":
        return getattr(stat, "st_blocks", (stat.st_size + 511) // 512) * 512
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCompressedFileSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.GetCompressedFileSizeW.restype = ctypes.c_uint32
    high = ctypes.c_uint32()
    ctypes.set_last_error(0)
    low = kernel.GetCompressedFileSizeW(str(path), ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.get_last_error():
        return stat.st_size
    return (high.value << 32) | low


def desktop_storage() -> dict:
    """Best-effort read-only detection. Settings JSON is not a stable public API."""
    default = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "Docker/wsl"
    result = {"folder": str(default), "configured": False, "settings": None, "disks": []}
    roaming = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "Docker"
    for name in ("settings-store.json", "settings.json"):
        path = roaming / name
        if not path.is_file():
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
            folder = config.get("dataFolder")
            if isinstance(folder, dict):
                folder = folder.get("value")
            if isinstance(folder, str) and Path(folder).is_absolute():
                result.update(folder=str(Path(folder)), configured=True, settings=str(path))
                break
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    result["disks"] = _vhdx_files(Path(result["folder"]))
    return result


def prepare_docker_move(engine, value: str | Path) -> dict:
    current = desktop_storage()
    target = destination_path(value, [engine.store.home, current["folder"], *engine.store.settings()["projects"]])
    total = sum(disk["allocated"] for disk in current["disks"])
    if shutil.disk_usage(_parent(target)).free < total + 256 * 1024**2:
        raise SPXError("Docker 迁移目标空间不足，请选择空间更大的磁盘。")
    with engine.store.lock():
        engine.doctor()
        engine._stop("已为 Docker 数据盘迁移停止工作区。迁移完成后请重新检查连接。")
        containers = engine.managed()
        images = engine.store.read("images.json", {})
        volumes = engine.docker.run("volume", "ls", "-q").splitlines()
        volumes = sorted(name for name in volumes if name.startswith(engine.prefix + "-"))
        owned = set(containers)
        other_running = [identifier for identifier in engine.docker.run("ps", "-q", "--no-trunc").splitlines() if identifier not in owned]
        target.mkdir(parents=True, exist_ok=True)
        _private_directory(target)
        with tempfile.TemporaryFile(dir=target) as probe:
            probe.write(b"ENGE SPX storage check")
        plan = {"schema": 1, "phase": "prepared", "target": str(target), "previous": current["folder"], "context": engine.docker.context, "instance": engine.store.instance, "containers": containers, "images": images, "volumes": volumes, "other_running": len(other_running), "prepared": time.time()}
        engine.store.write("docker-move.json", plan)
        return plan


def verify_docker_move(engine) -> dict:
    with engine.store.lock():
        plan = engine.store.read("docker-move.json")
        if not plan or plan.get("instance") != engine.store.instance or plan.get("context") != engine.docker.context:
            raise SPXError("请先选择目标位置并准备 Docker 迁移。")
        engine.doctor()
        for identifier in plan["containers"]:
            obj = engine.docker.inspect("container", identifier)
            if not obj:
                raise SPXError("迁移前的容器尚未找到。请在 Docker 中确认使用了原数据盘，暂勿重新安装环境。")
            engine.owned(obj)
        for identifier in plan["images"].values():
            if not engine.docker.inspect("image", identifier):
                raise SPXError("迁移前的运行镜像尚未找到。请在 Docker 中确认原数据已迁移，暂勿重新安装环境。")
        for name in plan["volumes"]:
            if not engine.docker.inspect("volume", name):
                raise SPXError("账号或浏览器数据卷尚未找到。请检查 Docker 数据盘位置，暂勿新建同名数据卷。")
        current = desktop_storage()
        target, folder = Path(plan["target"]).resolve(), Path(current["folder"]).resolve()
        located = current["configured"] and (folder == target or target in folder.parents) and bool(current["disks"])
        if not located:
            raise SPXError("Docker 已恢复且原资源均在，但尚未确认数据盘位于目标目录。请在 Docker 设置中完成 Disk image location 的 Apply，再点击核验。")
        plan.update(phase="verified", verified=time.time(), detected=current["folder"])
        engine.store.write("docker-move.json", plan)
        return plan
