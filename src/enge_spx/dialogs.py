"""Themed modal notices, with the same small API used by the controller."""
import tkinter as tk
from tkinter import ttk

from . import theme
from .window_frame import WindowFrame


def _show(title, message, parent=None, question=False, error=False):
    parent = parent or tk._default_root
    if parent is None:
        from tkinter import messagebox
        action = messagebox.askyesno if question else messagebox.showerror if error else messagebox.showinfo
        return action(title, message)
    parent = parent.winfo_toplevel()
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    result = False
    previous_grab = parent.grab_current()
    previous_focus = parent.focus_get()
    def finish(value=False):
        nonlocal result
        result = value
        dialog.destroy()
    chrome = WindowFrame(dialog, title=title, close=finish, resizable=False)
    frame = ttk.Frame(chrome.content, style="Panel.TFrame", padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="需要你的确认" if question else "操作未完成" if error else "提示", style="Eyebrow.TLabel").pack(anchor="w")
    ttk.Label(frame, text=title, font=(theme.FONT, 14, "bold")).pack(anchor="w", pady=(8, 14))
    text = str(message)
    if len(text) > 650 or text.count("\n") > 10:
        area = tk.Text(frame, background=theme.FIELD, foreground=theme.INK, relief="flat", wrap="word", font=(theme.FONT, 10), height=12, padx=12, pady=12, selectbackground=theme.ACCENT, selectforeground=theme.ACCENT_INK)
        area.insert("1.0", text)
        area.configure(state="disabled")
        area.pack(fill="both", expand=True)
    else:
        ttk.Label(frame, text=text, wraplength=450, justify="left").pack(anchor="w", fill="x")
    actions = ttk.Frame(frame, style="Panel.TFrame")
    actions.pack(fill="x", pady=(24, 0))
    if question:
        primary = ttk.Button(actions, text="确认继续", style="Accent.TButton", command=lambda: finish(True))
        primary.pack(side="right", padx=(10, 0))
        focus = ttk.Button(actions, text="暂不继续", command=finish)
        focus.pack(side="right")
    else:
        focus = ttk.Button(actions, text="知道了", style="Accent.TButton", command=lambda: finish(True))
        focus.pack(side="right")
    dialog.protocol("WM_DELETE_WINDOW", finish)
    dialog.bind("<Escape>", lambda event: finish())
    def enter(event):
        selected = dialog.focus_get()
        (selected if isinstance(selected, ttk.Button) else focus).invoke()
        return "break"
    dialog.bind("<Return>", enter)
    for button in actions.winfo_children():
        button.bind("<Return>", lambda event, target=button: (target.invoke(), "break")[1])
    dialog.update_idletasks()
    chrome.center(parent, 510, min(max(240, dialog.winfo_reqheight()), max(240, parent.winfo_screenheight() - 80)))
    dialog.deiconify()
    dialog.grab_set()
    dialog.focus_force()
    focus.focus_set()
    parent.wait_window(dialog)
    try:
        if previous_grab is not None and previous_grab.winfo_exists():
            previous_grab.grab_set()
        if previous_focus is not None and previous_focus.winfo_exists():
            previous_focus.focus_set()
    except tk.TclError:
        pass  # The application can be closed while a modal is waiting.
    return result


def askyesno(title, message, parent=None, **options):
    return _show(title, message, parent, question=True)


def showinfo(title, message, parent=None, **options):
    _show(title, message, parent)
    return "ok"


def showerror(title, message, parent=None, **options):
    _show(title, message, parent, error=True)
    return "ok"
