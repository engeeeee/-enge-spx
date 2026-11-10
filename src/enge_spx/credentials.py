"""Versioned, current-user Windows DPAPI storage. No portable-key substitute."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat

from .state import SPXError

FORMAT = "enge-spx-dpapi-json"
VERSION = 1
MAX_BYTES = 16 * 1024 * 1024
SENSITIVE_FILES = frozenset({"nodes.json", "settings.json", "runtime.json", "relay.json", "gateway/config.json", "browser-token.json"})


def check_path(home, name):
    """Refuse secret files redirected outside the application's private tree."""
    if name not in SENSITIVE_FILES:
        return
    path = Path(home) / name
    for item in (path, *[parent for parent in path.parents if Path(home) in parent.parents]):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise SPXError("凭据路径包含链接，操作已拒绝，原数据已保留。")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or info.st_size > MAX_BYTES * 2:
            raise SPXError("凭据文件类型或大小无效，原数据已保留。")


class DPAPI:
    def __init__(self):
        if os.name != "nt":
            raise SPXError("DPAPI 仅在 Windows 上可用；此平台使用私有文件权限。")
        from ctypes import wintypes
        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
        self.Blob = Blob
        self.crypt = ctypes.WinDLL("crypt32.dll", use_last_error=True, winmode=0x00000800)
        self.kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x00000800)
        self.crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self.crypt.CryptProtectData.restype = wintypes.BOOL
        self.crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        self.crypt.CryptUnprotectData.restype = wintypes.BOOL
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p

    def _blob(self, data):
        memory = ctypes.create_string_buffer(data)
        return self.Blob(len(data), ctypes.cast(memory, ctypes.POINTER(ctypes.c_ubyte))), memory

    def _run(self, data, entropy, decrypt=False):
        if not data or len(data) > MAX_BYTES + (4096 if decrypt else 0):
            raise SPXError("凭据数据大小无效，原配置未清除。")
        incoming, keep_input = self._blob(data)
        context, keep_context = self._blob(entropy)
        output = self.Blob()
        try:
            # UI_FORBIDDEN only. Never CRYPTPROTECT_LOCAL_MACHINE.
            args = (ctypes.byref(incoming), None if decrypt else "ENGE SPX credentials v1", ctypes.byref(context), None, None, 1, ctypes.byref(output))
            function = self.crypt.CryptUnprotectData if decrypt else self.crypt.CryptProtectData
            if not function(*args):
                operation = "解密" if decrypt else "加密"
                raise SPXError(f"Windows 凭据{operation}失败。请使用原 Windows 账户及其密钥，检查用户配置和目录权限；原数据未清除。")
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                ctypes.memset(output.pbData, 0, output.cbData)
                self.kernel.LocalFree(output.pbData)
            ctypes.memset(keep_input, 0, len(keep_input))
            ctypes.memset(keep_context, 0, len(keep_context))

    def protect(self, data, entropy):
        return self._run(data, entropy)

    def unprotect(self, data, entropy):
        return self._run(data, entropy, True)


class CredentialCodec:
    def __init__(self, instance, protector=None):
        self.instance = instance
        self.protector = protector if protector is not None else DPAPI() if os.name == "nt" else None

    @property
    def enabled(self):
        return self.protector is not None

    def entropy(self, name):
        return hashlib.sha256(("ENGE SPX\0credentials-v1\0" + self.instance + "\0" + name).encode("utf-8")).digest()

    def encode(self, name, value):
        if not self.enabled or name not in SENSITIVE_FILES:
            return value
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise SPXError("凭据数据过大，原配置未清除。")
        protected = self.protector.protect(data, self.entropy(name))
        return {"format": FORMAT, "version": VERSION, "scope": "current-user", "data": base64.b64encode(protected).decode("ascii")}

    def decode(self, name, value, required=False):
        protected = isinstance(value, dict) and str(value.get("format", "")).startswith("enge-spx-dpapi")
        if not protected:
            if required and name in SENSITIVE_FILES:
                raise SPXError("凭据保护格式发生变化。请保留数据并使用显式迁移或回滚流程，不能自动改用明文。")
            return value
        if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("scope") != "current-user" or name not in SENSITIVE_FILES:
            raise SPXError("凭据封套版本或用途不受支持，原数据未清除。")
        if not self.enabled:
            raise SPXError("此数据由 Windows DPAPI 保护，请使用原 Windows 账户恢复；不会将密文当作空配置。")
        try:
            if not isinstance(value.get("data"), str) or len(value["data"]) > MAX_BYTES * 2:
                raise ValueError()
            ciphertext = base64.b64decode(value["data"], validate=True)
            if not ciphertext or len(ciphertext) > MAX_BYTES + 4096:
                raise ValueError()
            plain = self.protector.unprotect(ciphertext, self.entropy(name))
            return json.loads(plain)
        except SPXError:
            raise
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            raise SPXError("凭据封套损坏或无法解密，原数据未清除。") from error

    def pending(self, home):
        if not self.enabled:
            return []
        pending = []
        for name in sorted(SENSITIVE_FILES):
            check_path(home, name)
            path = Path(home) / name
            if path.exists():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    raise SPXError("无法读取旧凭据文件，迁移未开始，原数据已保留。") from error
                self.decode(name, value)
                if not isinstance(value, dict) or value.get("format") != FORMAT:
                    pending.append(name)
        return pending
