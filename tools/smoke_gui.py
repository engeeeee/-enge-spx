"""Create and render the real Tk interface, then close without starting Docker."""
from pathlib import Path
import os
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

from enge_spx.gui import App
from enge_spx.downloads import DownloadPaused
from enge_spx.state import Store


with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(directory) / "local")}):
    root = tk.Tk()
    app = App(root, Store(Path(directory) / "private"), auto_check=False)
    app.auto_start_docker.set(False)  # Smoke tests must never start a real Desktop.
    root.update()
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
    app.show_page("overview")
    root.after(500, root.destroy)
    root.mainloop()
    print("GUI smoke check passed")
