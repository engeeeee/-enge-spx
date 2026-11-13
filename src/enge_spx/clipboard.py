"""On-demand Windows clipboard snapshots. No listener, history or content logs."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes as w
import os
import struct
import time

from .state import SPXError

MAX_TEXT = 8 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_FILES = 32


@dataclass(frozen=True)
class Snapshot:
    kind: str
    value: str | bytes | tuple[str, ...] = ""


def dib_to_bmp(data: bytes) -> bytes:
    """Add the missing BMP file header to CF_DIB/CF_DIBV5 (including bitfields)."""
    if len(data) < 40:
        raise SPXError("剪贴板位图头不完整。")
    size, width, height, planes, bits, compression = struct.unpack_from("<IiiHHI", data)
    if size not in (40, 52, 56, 108, 124) or len(data) < size or planes != 1 or width <= 0 or height == 0 or width * abs(height) > MAX_PIXELS:
        raise SPXError("剪贴板图片格式或尺寸不受支持。")
    if bits not in (1, 4, 8, 16, 24, 32) or compression not in (0, 3, 6):
        raise SPXError("剪贴板图片压缩格式不受支持。")
    colors = struct.unpack_from("<I", data, 32)[0]
    if colors > 256 or (bits <= 8 and colors > 2 ** bits):
        raise SPXError("剪贴板图片调色板无效。")
    palette = (colors or (2 ** bits if bits <= 8 else 0)) * 4
    masks = (16 if compression == 6 else 12) if size == 40 and compression in (3, 6) else 0
    offset = size + palette + masks
    needed = ((width * bits + 31) // 32) * 4 * abs(height)
    if offset > len(data) or needed > len(data) - offset:
        raise SPXError("剪贴板图片数据不完整。")
    return struct.pack("<2sIHHI", b"BM", 14 + len(data), 0, 0, 14 + offset) + data


def png_image(data: bytes, *, dib=False) -> bytes:
    # QImage is a value type and can be decoded/encoded in the paste worker.
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageReader
    if len(data) > MAX_IMAGE:
        raise SPXError("剪贴板图片超过 32 MiB。")
    source = QBuffer()
    source.setData(dib_to_bmp(data) if dib else data)
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source, b"bmp" if dib else b"png")
    reader.setAutoDetectImageFormat(False)
    size = reader.size()
    # Qt reports a negative height for valid top-down BMP/DIB images.
    width, height = size.width(), abs(size.height()) if dib else size.height()
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise SPXError("剪贴板图片无效或超过 4000 万像素。")
    image = reader.read()
    if image.isNull():
        raise SPXError("无法读取剪贴板图片。")
    result = QByteArray()
    target = QBuffer(result)
    target.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(target, "PNG") or result.size() > MAX_IMAGE:
        raise SPXError("无法生成 PNG，或图片超过 32 MiB。")
    return bytes(result)


class WindowsClipboard:
    def __init__(self):
        if os.name != "nt":
            raise SPXError("智能系统剪贴板需要 Windows。")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.user.OpenClipboard.argtypes = [w.HWND]
        self.user.OpenClipboard.restype = w.BOOL
        self.user.CloseClipboard.restype = w.BOOL
        self.user.GetClipboardSequenceNumber.restype = w.DWORD
        self.user.IsClipboardFormatAvailable.argtypes = [w.UINT]
        self.user.GetClipboardData.argtypes = [w.UINT]
        self.user.GetClipboardData.restype = w.HANDLE
        self.user.RegisterClipboardFormatW.argtypes = [w.LPCWSTR]
        self.user.RegisterClipboardFormatW.restype = w.UINT
        self.kernel.GlobalSize.argtypes = [w.HANDLE]
        self.kernel.GlobalSize.restype = ctypes.c_size_t
        self.kernel.GlobalLock.argtypes = [w.HANDLE]
        self.kernel.GlobalLock.restype = ctypes.c_void_p
        self.kernel.GlobalUnlock.argtypes = [w.HANDLE]
        self.shell.DragQueryFileW.argtypes = [w.HANDLE, w.UINT, w.LPWSTR, w.UINT]
        self.shell.DragQueryFileW.restype = w.UINT
        self.png = self.user.RegisterClipboardFormatW("PNG")

    def sequence(self) -> int:
        return self.user.GetClipboardSequenceNumber()

    def _data(self, fmt: int, limit: int) -> bytes:
        handle = self.user.GetClipboardData(fmt)
        if not handle:
            raise SPXError("无法读取剪贴板数据，请重新复制后粘贴。")
        length = self.kernel.GlobalSize(handle)
        if length == 0 or length > limit:
            raise SPXError("剪贴板数据为空或超过大小限制。")
        pointer = self.kernel.GlobalLock(handle)
        if not pointer:
            raise SPXError("剪贴板数据被占用，请重试。")
        try:
            return ctypes.string_at(pointer, length)
        finally:
            self.kernel.GlobalUnlock(handle)

    def read(self, expected_sequence=None) -> Snapshot:
        deadline = time.monotonic() + .25
        while not self.user.OpenClipboard(None):
            if time.monotonic() >= deadline:
                raise SPXError("剪贴板正被其他程序占用，请重试粘贴。")
            time.sleep(.01)
        try:
            if expected_sequence is not None and self.sequence() != expected_sequence:
                raise SPXError("剪贴板已改变，本次粘贴取消，请重新粘贴。")
            if self.user.IsClipboardFormatAvailable(15):  # CF_HDROP wins over preview/text
                handle = self.user.GetClipboardData(15)
                if not handle:
                    raise SPXError("无法读取剪贴板文件列表。")
                count = self.shell.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
                if not 0 < count <= MAX_FILES:
                    raise SPXError("每次可粘贴 1–32 个文件。")
                paths = []
                for i in range(count):
                    length = self.shell.DragQueryFileW(handle, i, None, 0)
                    if not 0 < length < 32768:
                        raise SPXError("剪贴板文件路径无效。")
                    buf = ctypes.create_unicode_buffer(length + 1)
                    if self.shell.DragQueryFileW(handle, i, buf, length + 1) != length:
                        raise SPXError("剪贴板文件列表不完整。")
                    paths.append(buf.value)
                return Snapshot("files", tuple(paths))
            for fmt, dib in ((self.png, False), (17, True), (8, True)):
                if fmt and self.user.IsClipboardFormatAvailable(fmt):
                    data = self._data(fmt, MAX_IMAGE)
                    # Release the clipboard before image decoding/encoding.
                    break
            else:
                if self.user.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
                    data = self._data(13, MAX_TEXT * 2)
                    if len(data) % 2:
                        raise SPXError("剪贴板 Unicode 文字无效。")
                    return Snapshot("text", data.decode("utf-16-le", errors="replace").split("\0", 1)[0])
                return Snapshot("empty")
        finally:
            self.user.CloseClipboard()
        return Snapshot("image", png_image(data, dib=dib))
