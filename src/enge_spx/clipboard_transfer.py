"""Session-bound streaming imports and native CLI paste frames."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
import uuid

from .brand import PACKAGE_RESOURCES
from .clipboard import MAX_IMAGE, MAX_PIXELS, Snapshot
from .state import SPXError

MAX_FILE = 128 * 1024 * 1024
MAX_BATCH = 256 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class Attachment:
    path: str
    image: bool
    name: str = ""


def text_frame(text: str) -> bytes:
    # Never allow clipboard bytes to terminate bracketed paste or inject keys.
    text = "".join(c for c in text if c in "\r\n\t" or 32 <= ord(c) < 127 or ord(c) >= 160)
    return b"\x1b[200~" + text.encode("utf-8", errors="replace") + b"\x1b[201~"


class InputAdapter:
    # Exact, reproducible compatibility targets; user-installed upgrades are
    # detected rather than silently assumed to keep image-path semantics.
    VERIFIED = {"claude": {(2, 1, 319)}, "codex": {(0, 167, 0)}}

    def __init__(self, tool, version):
        self.tool = tool
        self.version = tuple(version)

    def frames(self, attachments):
        return [data for data, image in self.events(attachments)]

    def events(self, attachments):
        if self.tool not in self.VERIFIED:
            raise SPXError("图片和文件智能粘贴仅用于 Claude Code / Codex 的输入区。")
        if any(x.image for x in attachments) and self.version not in self.VERIFIED[self.tool]:
            raise SPXError("当前 CLI 版本的原生图片粘贴尚未验证；本次未插入，请使用已验证版本或更新适配器。")
        result = []
        for item in attachments:
            if not re.fullmatch(r"/(?:workspace/[a-f0-9]{16}/\.enge-spx-clipboard|tmp/enge-spx-clipboard-[a-f0-9]{16})/[a-f0-9]{32}/[a-f0-9]{32}(?:\.[a-z0-9]{1,12})?", item.path):
                raise SPXError("附件路径不属于本次受控导入。")
            # Both pinned TUIs classify a standalone image path paste as an
            # image, not literal text. Each image needs its own Paste event.
            label = json.dumps(item.name[:240], ensure_ascii=False) if item.name else ""
            if item.image:
                if label:
                    result.append((text_frame(" 图片 " + label + " "), False))
                result.append((text_frame(item.path), True))
            else:
                value = (" 文件 " + label + ": " if label else " ") + ("@" if self.tool == "claude" else "") + item.path + " "
                result.append((text_frame(value), False))
        return result


@contextmanager
def open_source(path):
    """Hold a regular source file for the entire transfer, never follow its link."""
    path = Path(path)
    if os.name == "nt":
        from .clipboard_file_windows import open_read
        fd = open_read(path)
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not 0 <= info.st_size <= MAX_FILE:
            raise SPXError("只接受不超过 128 MiB 的普通文件；目录、链接和设备不导入。")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            yield stream, info.st_size
    finally:
        if fd is not None:
            os.close(fd)


def validate_image(stream, size):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImageReader
    if size > MAX_IMAGE:
        raise SPXError("单张图片超过 32 MiB。")
    data = stream.read(MAX_IMAGE + 1)
    if len(data) != size:
        raise SPXError("图片在读取期间发生变化。")
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    dimensions = reader.size()
    if not dimensions.isValid() or dimensions.width() * dimensions.height() > MAX_PIXELS or reader.read().isNull():
        raise SPXError("图片损坏、格式不支持或超过 4000 万像素。")
    return io.BytesIO(data)


class Transfer:
    def __init__(self, engine, project, tool, session, container):
        self.engine, self.project, self.tool = engine, project, tool
        self.session, self.container = session, container
        self.bridge = uuid.uuid4().hex
        from .workspace_profiles import project_plan
        self.plan = project_plan(engine, project)
        self.version = None
        self.cancelled = threading.Event()
        self.process = None
        self.lease = None
        self.last_images = []
        self.last_paths = []

    def close(self):
        self.cancelled.set()
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        if self.lease is not None:
            self.lease.close()

    def verify(self):
        if self.cancelled.is_set():
            raise SPXError("终端已关闭，粘贴已取消。")
        # Reuse the exact owned container, topology, identity, mounts and live
        # guard checks used to attach the CLI. Never create/start anything.
        self.engine.attach_command(self.project, self.tool, self.session, self.container, interactive=True)
        from .workspace_profiles import project_plan
        if project_plan(self.engine, self.project) != self.plan:
            raise SPXError("项目身份或权限已改变，已取消粘贴。")

    def adapter(self):
        # --version creates no interactive session. Query once per import so a
        # user update followed by restarting the CLI in this terminal cannot
        # inherit a stale compatibility decision.
        from .tool_session import PREPARE
        value = self.engine.docker.run("exec", self.container, "bash", "--noprofile", "--norc", "-c", PREPARE + 'exec "$@" --version\n', "enge-spx-version", self.tool, timeout=10)
        match = re.fullmatch(r"(?:codex-cli\s+)?(\d+)\.(\d+)\.(\d+)(?:\s+\(Claude Code\))?\s*", value)
        self.version = tuple(map(int, match.groups())) if match else ()
        return InputAdapter(self.tool, self.version)

    def paste(self, snapshot: Snapshot):
        if snapshot.kind not in ("image", "files"):
            raise SPXError("此粘贴不包含图片或文件。")
        self.verify()
        with ExitStack() as stack:
            streams, files, images, labels, total = [], [], [], [], 0
            sources = (None,) if snapshot.kind == "image" else snapshot.value
            if not isinstance(sources, tuple) or not 1 <= len(sources) <= 32:
                raise SPXError("每次可导入 1–32 个文件。")
            for source in sources:
                if source is None:
                    if not isinstance(snapshot.value, bytes) or len(snapshot.value) > MAX_IMAGE:
                        raise SPXError("剪贴板图片超过限制。")
                    stream, size, extension = io.BytesIO(snapshot.value), len(snapshot.value), ".png"
                    labels.append("截图.png")
                else:
                    stream, size = stack.enter_context(open_source(source))
                    extension = Path(source).suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,12}", extension):
                        extension = ""
                    labels.append(Path(source).name)
                image = extension in IMAGE_SUFFIXES
                total += size
                if total > MAX_BATCH:
                    raise SPXError("本次粘贴总大小超过 256 MiB。")
                if image:
                    stream = validate_image(stream, size)
                streams.append(stream)
                files.append({"name": uuid.uuid4().hex + extension, "size": size})
                images.append(image)
            if sum(f["size"] for f in files) > MAX_BATCH:
                raise SPXError("本次粘贴总大小超过 256 MiB。")
            adapter = self.adapter()
            # Reject unsupported image versions before copying any files.
            if any(images) and adapter.version not in adapter.VERIFIED.get(self.tool, set()):
                raise SPXError("当前 CLI 版本尚未验证原生图片粘贴；未复制或插入附件。")
            if self.lease is None:
                from .clipboard_cache import CacheLease
                self.lease = CacheLease(self.engine.store, self.bridge, self.plan, self.container)
            if self.cancelled.is_set():
                self.lease.close()
                raise SPXError("终端已关闭，导入已取消。")
            header = {"schema": 1, "project": self.plan["key"], "access": self.plan["access"], "bridge": self.bridge, "files": files, "prune": self.lease.expired()}
            script = (PACKAGE_RESOURCES / "checks/clipboard_transfer.py").read_text(encoding="utf-8")
            command = self.engine.docker.command("exec", "-i", "--workdir", "/workspace/" + self.plan["key"], self.container, "python3", "-I", "-c", script)
            result = self._stream(command, header, streams)
            paths = result["paths"]
            if not isinstance(result["pruned"], list) or any(x not in header["prune"] for x in result["pruned"]):
                raise SPXError("附件清理响应核验失败。")
            self.lease.forget(result["pruned"])
        self.verify()
        expected = ("/workspace/" + self.plan["key"] + "/.enge-spx-clipboard/" if self.plan["access"] == "rw" else "/tmp/enge-spx-clipboard-" + self.plan["key"] + "/") + self.bridge + "/"
        if paths != [expected + f["name"] for f in files]:
            raise SPXError("容器附件路径核验失败，未插入输入框。")
        self.last_paths = paths
        events = adapter.events([Attachment(path, image, label) for path, image, label in zip(paths, images, labels)])
        self.last_images = [image for data, image in events]
        return [data for data, image in events]

    def _stream(self, command, header, streams):
        # stdout/stderr are bounded, private captures, never raw exception/log
        # output. A watchdog interrupts only this owned docker exec client.
        hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "HOME", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "DOCKER_CONFIG"}
            environment = {key: value for key, value in self.engine.docker.environment().items() if key.upper() in allowed}
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err, env=environment, creationflags=hidden)
            self.process = process
            if self.cancelled.is_set():
                process.kill()
            expired = threading.Event()
            def timeout():
                expired.set()
                try:
                    process.kill()
                except OSError:
                    pass
            watchdog = threading.Timer(120, timeout)
            watchdog.daemon = True
            watchdog.start()
            try:
                process.stdin.write(json.dumps(header).encode("ascii") + b"\n")
                for item, stream in zip(header["files"], streams):
                    left, digest = item["size"], hashlib.sha256()
                    while left:
                        block = stream.read(min(left, 1024 * 1024))
                        if not block:
                            raise SPXError("文件在复制期间发生变化，未插入输入框。")
                        process.stdin.write(block)
                        digest.update(block)
                        left -= len(block)
                    process.stdin.write(digest.digest())
                process.stdin.close()
                process.wait(timeout=125)
                if process.returncode or expired.is_set():
                    raise SPXError("文件导入失败或超时，请检查工作区、权限及 1 GiB 附件缓存上限。当前输入保留。")
                out.seek(0)
                data = out.read(16385)
                result = json.loads(data) if len(data) <= 16384 else {}
                if set(result) != {"schema", "paths", "pruned"} or result["schema"] != 1 or not isinstance(result["paths"], list):
                    raise SPXError("附件导入响应无效。当前输入保留。")
                return result
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise SPXError("文件复制失败。当前输入保留，请确认文件未被占用后重试。") from error
            finally:
                watchdog.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                self.process = None
