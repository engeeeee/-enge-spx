"""Create and render the real Tk interface, then close without starting Docker."""
from pathlib import Path
import os
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from enge_spx.gui import App
from enge_spx.state import Store


with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": str(Path(directory) / "local")}):
    root = tk.Tk()
    app = App(root, Store(Path(directory) / "private"), auto_check=False)
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
    app.show_page("overview")
    root.after(500, root.destroy)
    root.mainloop()
    print("GUI smoke check passed")
