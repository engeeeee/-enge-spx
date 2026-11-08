"""Create and render the real Tk interface, then close without starting Docker."""
from pathlib import Path
import tempfile
import tkinter as tk

from enge_spx.gui import App
from enge_spx.state import Store


with tempfile.TemporaryDirectory() as directory:
    root = tk.Tk()
    app = App(root, Store(Path(directory)), auto_check=False)
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
    app.show_page("overview")
    root.after(500, root.destroy)
    root.mainloop()
    print("GUI smoke check passed")
