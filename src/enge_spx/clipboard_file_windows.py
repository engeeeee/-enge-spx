"""Open a local clipboard file without traversing any filesystem reparse point.

Anchor at a local drive root, then use documented NtCreateFile object flags.
Unlike a check-then-CreateFile path walk, OBJ_DONT_REPARSE also rejects a link
introduced concurrently in an intermediate component.
"""
import ctypes
from ctypes import wintypes as w
import os
import re

from .state import SPXError


class UnicodeString(ctypes.Structure):
    _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", w.LPWSTR)]


class ObjectAttributes(ctypes.Structure):
    _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE), ("ObjectName", ctypes.POINTER(UnicodeString)),
                ("Attributes", w.ULONG), ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]


class IoStatus(ctypes.Structure):
    _fields_ = [("StatusOrPointer", ctypes.c_void_p), ("Information", ctypes.c_size_t)]


def open_read(value):
    import msvcrt
    value = str(value).replace("/", "\\")
    if not re.match(r"^[A-Za-z]:\\", value) or ":" in value[2:] or any(c in value for c in ("\0", "\r", "\n")):
        raise SPXError("仅支持本机磁盘普通文件，不支持网络路径、设备或数据流。")
    relative = value[3:]
    if not relative or any(x in ("", ".", "..") for x in relative.split("\\")) or len(relative.encode("utf-16-le")) > 65532:
        raise SPXError("剪贴板文件路径无效。")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    native = ctypes.WinDLL("ntdll")
    api.GetDriveTypeW.argtypes, api.GetDriveTypeW.restype = [w.LPCWSTR], w.UINT
    api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    api.CreateFileW.restype = w.HANDLE
    api.CloseHandle.argtypes = [w.HANDLE]
    native.NtCreateFile.argtypes = [ctypes.POINTER(w.HANDLE), w.ULONG, ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatus), ctypes.c_void_p,
                                   w.ULONG, w.ULONG, w.ULONG, w.ULONG, ctypes.c_void_p, w.ULONG]
    native.NtCreateFile.restype = ctypes.c_int32
    if api.GetDriveTypeW(value[:3]) not in (2, 3):  # removable/fixed; never SMB
        raise SPXError("剪贴板文件必须位于本机磁盘。")
    root = api.CreateFileW(value[:3], 0x00100001, 7, None, 3, 0x02000000 | 0x00200000, None)
    if root == ctypes.c_void_p(-1).value:
        raise SPXError("无法打开源文件所在磁盘，请检查权限。")
    handle = w.HANDLE()
    try:
        size = len(relative.encode("utf-16-le"))
        buffer = ctypes.create_unicode_buffer(relative, size // 2 + 1)
        name = UnicodeString(size, size + 2, ctypes.cast(buffer, w.LPWSTR))
        attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), root, ctypes.pointer(name), 0x1040, None, None)
        status = IoStatus()
        result = native.NtCreateFile(ctypes.byref(handle), 0x00120089, ctypes.byref(attributes), ctypes.byref(status), None, 0, 1, 1, 0x64, None, 0)
        if result < 0:
            raise SPXError("无法读取所复制文件：权限不足、文件占用或路径包含链接/云占位符。")
        try:
            return msvcrt.open_osfhandle(handle.value, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            api.CloseHandle(handle)
            raise
    finally:
        api.CloseHandle(root)
