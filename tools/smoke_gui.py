"""Create and render the real Tk interface, then close without starting Docker."""
from pathlib import Path
import faulthandler
import os
import json
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

from enge_spx.gui import App
from enge_spx.downloads import DownloadPaused
from enge_spx.state import Store
from enge_spx import dialogs
from enge_spx.platform_ui import prepare_windows

faulthandler.dump_traceback_later(60, exit=True)

def capture(root, name):
    directory = os.environ.get("SPX_UI_REPORT_DIR")
    if not directory or os.name != "nt":
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    root.lift()
    root.update()
    script = f'''
Add-Type -AssemblyName System.Drawing
$spxCapture = New-Object System.Drawing.Bitmap({root.winfo_width()}, {root.winfo_height()})
$spxGraphics = [System.Drawing.Graphics]::FromImage($spxCapture)
try {{
    $spxGraphics.CopyFromScreen({root.winfo_rootx()}, {root.winfo_rooty()}, 0, 0, $spxCapture.Size)
    $spxCapture.Save($env:SPX_CAPTURE_IMAGE, [System.Drawing.Imaging.ImageFormat]::Png)
}} finally {{
    $spxGraphics.Dispose()
    $spxCapture.Dispose()
}}
'''
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env={**os.environ, "SPX_CAPTURE_IMAGE": str(target / (name + ".png"))}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (target / (name + ".png")).is_file()


with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(directory) / "local")}):
    prepare_windows()
    root = tk.Tk()
    app = App(root, Store(Path(directory) / "private"), auto_check=False)
    app.auto_start_docker.set(False)  # Smoke tests must never start a real Desktop.
    root.update()
    assert app.next_button.winfo_viewable(), "Main action must render inside its card"
    assert app.chrome.controls["close"].winfo_viewable()
    if os.name == "nt":
        assert app.chrome.native and app.chrome.native.active
        import ctypes
        from enge_spx.window_frame import MonitorInfo, Rect
        native = app.chrome.native
        area, bounds = MonitorInfo(size=ctypes.sizeof(MonitorInfo)), Rect()
        native.user.GetMonitorInfoW(native.user.MonitorFromWindow(native.hwnd, 2), ctypes.byref(area))
        native.user.GetWindowRect(native.hwnd, ctypes.byref(bounds))
        assert bounds.top >= area.work.top and bounds.bottom <= area.work.bottom, "Initial window overlaps the taskbar or leaves the work area"
    capture(root, "overview")
    print("GUI initial layout passed", flush=True)
    assert len(app.buttons) >= 12
    assert app.phase.get()
    assert app.settings_match()
    app.timezone.set("Etc/UTC")
    assert not app.settings_match()
    app.poll()
    assert app.confirm_button.instate(["disabled"])
    for page in app.pages:
        app.show_page(page)
        root.update()
        first = app.pages[page].content.winfo_children()[0]
        assert first.winfo_height() > 40, "Page card did not measure its content"
        assert first.content.winfo_viewable(), "Page content is hidden"
        if page in ("connection", "workspace"):
            capture(root, page)
    assert "Pebrel" in app.terminal_box["values"]
    app.terminal_kind.set("Pebrel")
    app.terminal_changed()
    assert app.terminal_args_entry.instate(["disabled"])
    app.terminal_kind.set("自定义程序")
    app.terminal_fields()
    assert not app.terminal_args_entry.instate(["disabled"])
    app.timezone.set(app.store.settings()["timezone"])
    original = app.store.home
    target = Path(directory) / "moved data"
    app.data_target.set(str(target))
    with patch("enge_spx.gui.messagebox.askyesno", return_value=True), patch("enge_spx.gui.messagebox.showerror", side_effect=AssertionError("GUI migration failed")):
        app.migrate_data()
        deadline = time.monotonic() + 15
        while app.store.home != target.resolve() and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
    assert app.store.home == target.resolve()
    assert app.data_location.get() == str(target.resolve())
    assert Store(original).instance == app.store.instance
    assert Store().home == target.resolve()
    print("GUI migration passed", flush=True)

    # Exercise the actual asynchronous startup UI without Docker or downloads.
    def settle():
        deadline = time.monotonic() + 10
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        assert not app.busy, "GUI operation did not finish"
    settle()
    entered, release = threading.Event(), threading.Event()
    def fake_prepare(engine, settings, progress, cancel, **options):
        progress({"stage": "docker_wait", "message": "Waiting in isolated GUI smoke"})
        entered.set()
        assert release.wait(5), "GUI did not remain responsive"
        progress({"stage": "configure", "message": "Add a landing"})
        return {"phase": "needs_configuration", "runtime": True, "docker": {"docker": "29.0.0", "architecture": "x86_64"}}
    with patch("enge_spx.gui.prepare_workspace", side_effect=fake_prepare), patch.object(app, "proxy_dialog") as configure:
        app.prepare()
        assert entered.wait(2)
        root.update()
        app.render()
        assert app.startup_cancel.instate(["!disabled"])
        assert app.next_button.instate(["disabled"])
        release.set()
        settle()
        assert app.docker_ready and app.runtime_ok
        assert app.page_name == "connection"
        configure.assert_called_once()

    def wait_for_cancel(engine, settings, progress, cancel, **options):
        assert cancel.wait(5)
        raise DownloadPaused("GUI startup cancelled; data retained")
    with patch("enge_spx.gui.prepare_workspace", side_effect=wait_for_cancel):
        app.prepare()
        app.pause()
        settle()
    assert not app.startup_active
    assert app.startup_title.get() == "准备已取消"
    assert app.store.instance == Store(original).instance
    print("GUI asynchronous preparation passed", flush=True)

    app.chrome.controls["maximize"].invoke()
    root.update()
    assert app.chrome.maximized()
    app.chrome.restore()
    root.update()
    assert not app.chrome.maximized()
    if os.name == "nt":
        app.chrome.controls["minimize"].invoke()
        root.update()
        assert app.chrome.native.user.IsIconic(app.chrome.native.hwnd)
        app.chrome.restore()
        root.update()
    print("GUI window controls passed; Tk state=" + root.state(), flush=True)

    def answer_modal(accept=False, enter=False):
        def visit(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Toplevel):
                    return child
                found = visit(child)
                if found:
                    return found
        dialog = visit(root)
        assert dialog is not None, "Themed modal did not open"
        assert dialog._spx_frame.controls["close"].winfo_viewable()
        if enter:
            assert dialog.focus_get().cget("text") == "暂不继续", "Default confirmation focus must be Cancel"
            dialog.event_generate("<Return>")
        elif accept:
            def click(widget):
                from tkinter import ttk
                if isinstance(widget, ttk.Button) and widget.cget("text") == "确认继续":
                    widget.invoke()
                    return True
                return any(click(c) for c in widget.winfo_children())
            assert click(dialog)
        else:
            dialog._spx_frame.controls["close"].invoke()
    root.grab_set()
    print("GUI modal checks starting", flush=True)
    root.after(120, lambda: answer_modal(accept=True))
    assert dialogs.askyesno("界面确认检查", "本次检查不访问 Docker。", parent=root)
    assert root.grab_current() == root
    root.after(120, answer_modal)
    assert not dialogs.askyesno("界面取消检查", "关闭弹窗应取消。", parent=root)
    root.after(120, lambda: answer_modal(enter=True))
    assert not dialogs.askyesno("键盘默认检查", "默认聚焦取消按钮。", parent=root)
    root.grab_release()
    if os.environ.get("SPX_UI_REPORT_DIR"):
        report = {"custom_frame": True, "native_frame": bool(app.chrome.native and app.chrome.native.active), "maximize_restore": True, "minimize_restore": os.name == "nt", "modal_confirm_cancel": True, "default_confirmation_is_cancel": True, "all_pages_visible": True}
        target = Path(os.environ["SPX_UI_REPORT_DIR"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "ui-checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    app.show_page("overview")
    root.after(500, root.destroy)
    root.mainloop()
    faulthandler.cancel_dump_traceback_later()
    print("GUI smoke check passed")
