"""Bounded, local GUI fault records, including windowed executables without stderr."""
from contextlib import contextmanager
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import traceback

from . import __version__
from .state import relocated_home

log = logging.getLogger("enge_spx.gui")


class GuiDiagnostics:
    def __init__(self, home):
        self.home = Path(home)
        self.handler = self.fault = None
        self.previous_level = log.level
        self.previous_fault_handler = faulthandler.is_enabled()

    @property
    def directory(self):
        return self.home / "logs"

    def __enter__(self):
        self.open()
        return self

    def open(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(self.directory / "gui.log", maxBytes=256 * 1024, backupCount=2, encoding="utf-8")
            self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s %(message)s"))
            log.addHandler(self.handler)
            log.setLevel(logging.INFO)
            path = self.directory / "gui-fault.log"
            if path.exists() and path.stat().st_size >= 1024 * 1024:
                path.replace(path.with_suffix(".log.1"))
            self.fault = path.open("a", encoding="utf-8", buffering=1)
            self.fault.write(f"ENGE SPX {__version__} GUI session pid={os.getpid()} python={sys.version.split()[0]}\n")
            faulthandler.enable(file=self.fault, all_threads=True)
            log.info("gui-start version=%s", __version__)
        except (OSError, RuntimeError):
            # A diagnostics failure must not prevent the application opening.
            self.close()

    def capture(self, kind, exc_type, error, tb):
        # Do not include exception messages or frame locals: a URL or command
        # can contain proxy credentials. Native fault dumps also omit locals.
        frames = "".join(f"  {frame.filename}:{frame.lineno} in {frame.name}\n" for frame in traceback.extract_tb(tb))
        log.error("%s type=%s\n%s", kind, exc_type.__name__, frames)

    def attach(self, root):
        showing_error = False
        self.previous_exception_hook = sys.excepthook

        def callback_error(exc_type, error, tb):
            nonlocal showing_error
            if exc_type is KeyboardInterrupt:
                log.info("gui-keyboard-interrupt")
                root.c.cancel.set()
                root.finish_close()
                return
            self.capture("gui-callback-error", exc_type, error, tb)
            if showing_error:
                return
            showing_error = True
            try:
                from .ui.widgets import notice
                notice(root, "ENGE SPX 界面异常", f"界面操作出现异常，诊断日志保存在：\n{self.directory}\n\n请保留日志并反馈发生异常前的操作。", True)
            finally:
                showing_error = False

        sys.excepthook = callback_error

    def observe(self, app):
        """Distinguish a live hidden window from an exited or blocked process."""
        from PySide6.QtCore import QTimer
        root = app
        previous = None

        def heartbeat():
            nonlocal previous
            try:
                state = (root.isVisible(), root.isMinimized(), root.isActiveWindow(),
                         root.c.busy, root.c.startup_active, root.c.docker_ready)
                if state != previous:
                    log.info("gui-state visible=%s minimized=%s active=%s busy=%s preparing=%s docker-ready=%s", *state)
                    previous = state
                else:
                    log.info("gui-heartbeat")
            except Exception as error:
                self.capture("gui-observer-error", type(error), error, error.__traceback__)

        self.observer = QTimer(root)
        self.observer.setInterval(5000)
        self.observer.timeout.connect(heartbeat)
        self.observer.start()

    @contextmanager
    def suspended_for_migration(self):
        # Windows cannot delete open log files. Close before the verified copy,
        # then follow the committed redirect on success or reopen the source.
        self.close()
        try:
            yield
        finally:
            self.home = relocated_home(self.home)
            self.open()

    def close(self):
        if self.fault is not None:
            faulthandler.disable()
            self.fault.close()
            self.fault = None
            if self.previous_fault_handler and sys.stderr is not None:
                faulthandler.enable()
        if self.handler is not None:
            log.removeHandler(self.handler)
            self.handler.close()
            self.handler = None
        log.setLevel(self.previous_level)

    def __exit__(self, exc_type, error, tb):
        if exc_type is KeyboardInterrupt:
            log.info("gui-stop keyboard-interrupt")
        elif exc_type is not None:
            self.capture("gui-unhandled-error", exc_type, error, tb)
        else:
            log.info("gui-stop normal")
        self.close()
        if hasattr(self, "previous_exception_hook"):
            sys.excepthook = self.previous_exception_hook
