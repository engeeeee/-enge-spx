"""Versioned public terminal preferences, independent of proxy credentials."""
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .state import SPXError

FILE = "terminal-preferences.json"
DEFAULTS = {"font_size": 11, "font_family": "", "copy_on_select": True, "right_click_paste": True,
            "appearance": "solid", "tint": "clay", "opacity": 85}
TINTS = {"clay": "#1c1a18", "purple": "#302034", "graphite": "#1d252c"}


def validate(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1 or set(value) - {"schema", *DEFAULTS}:
        raise SPXError("终端偏好格式无效，原文件已保留；可在右上角恢复默认设置。")
    result = {**DEFAULTS, **{key: value[key] for key in DEFAULTS if key in value}}
    if type(result["font_size"]) is not int or not 8 <= result["font_size"] <= 24 or type(result["opacity"]) is not int or not 55 <= result["opacity"] <= 100:
        raise SPXError("终端字号或背景不透明度超出范围，原设置已保留。")
    if not isinstance(result["font_family"], str) or len(result["font_family"]) > 80 or any(ord(c) < 32 for c in result["font_family"]):
        raise SPXError("终端字体设置无效，原文件已保留。")
    if any(type(result[key]) is not bool for key in ("copy_on_select", "right_click_paste")) or not isinstance(result["appearance"], str) or not isinstance(result["tint"], str) or result["appearance"] not in ("solid", "acrylic") or result["tint"] not in TINTS:
        raise SPXError("终端外观或鼠标设置无效，原文件已保留。")
    return result


def read(store):
    if store is not None:
        from .credentials import check_path
        check_path(store.home, FILE)
        path = store.home / FILE
        if path.exists() and path.stat().st_size > 65536:
            raise SPXError("终端偏好文件异常过大，原文件已保留。")
    return validate(store.read(FILE, {"schema": 1})) if store is not None else dict(DEFAULTS)


def save(store, patch, reset=False):
    with store.lock("terminal-preferences", timeout=2):
        from .credentials import check_path
        check_path(store.home, FILE)
        current = dict(DEFAULTS) if reset else read(store)
        updated = validate({"schema": 1, **current, **patch})
        if reset and (store.home / FILE).exists():
            # Keep the original public settings for recovery, including a
            # malformed file. Never copy proxy/account configuration here.
            source = store.home / FILE
            with source.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise SPXError("终端偏好文件异常过大，未覆盖原文件。")
            store.write("terminal-preferences-previous.json", {"schema": 1, "raw_utf8": raw.decode("utf-8", errors="replace")})
        store.write(FILE, {"schema": 1, **updated})
        return updated


class Preferences(QObject):
    changed = Signal(object)
    error = Signal(str)

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.load_error = None
        try:
            self.value = read(store)
        except (OSError, SPXError) as error:
            self.value, self.load_error = dict(DEFAULTS), str(error)
        self.dirty, self.waiting = {}, {}
        self.worker_lock = threading.Lock()
        self.worker = None
        self.reset_pending = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.flush)

    def set(self, key, value):
        if self.value.get(key) == value:
            return
        self.value = validate({"schema": 1, **self.value, key: value})
        self.dirty[key] = value
        self.changed.emit(dict(self.value))
        if self.load_error:
            self.error.emit(self.load_error)
        else:
            self.timer.start()

    def reset(self):
        self.value = dict(DEFAULTS)
        self.dirty = dict(DEFAULTS)
        self.reset_pending, self.load_error = True, None
        self.changed.emit(dict(self.value))
        self.flush()

    def flush(self):
        self.timer.stop()
        if not self.dirty or self.store is None or self.load_error:
            return
        with self.worker_lock:
            self.waiting.update(self.dirty)
            self.dirty.clear()
            if self.worker is not None:
                return
            # Bounded, non-daemon saving finishes when the last window closes.
            # Only a small merged map is queued, never input or clipboard data.
            self.worker = threading.Thread(target=self._save, name="spx-terminal-preferences")
            self.worker.start()

    def _save(self):
        while True:
            with self.worker_lock:
                if not self.waiting:
                    self.worker = None
                    return
                patch, self.waiting = self.waiting, {}
                reset, self.reset_pending = self.reset_pending, False
            try:
                save(self.store, patch, reset)
            except (OSError, SPXError):
                try:
                    self.error.emit("终端偏好未保存，请检查数据目录权限后重试；当前显示设置仍保留。")
                except RuntimeError:
                    pass  # The owning window has already closed.
