"""Shared warm-black and amber styling for the desktop interface."""
import tkinter as tk
import os
from tkinter import scrolledtext, ttk

BG = "#101211"
SIDEBAR = "#151716"
SURFACE = "#1B1E1B"
FIELD = "#141714"
HOVER = "#282D26"
INK = "#EEEDE5"
MUTED = "#A3A79C"
FAINT = "#697064"
ACCENT = "#EBC45B"
ACCENT_HOVER = "#F6D779"
ACCENT_INK = "#211D10"
ACCENT_SURFACE = "#302D1E"
BORDER = "#32372E"
SUCCESS = "#9CC78D"
DANGER = "#E9917F"
FONT = "Microsoft YaHei UI" if os.name == "nt" else "Segoe UI"


def apply(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    for name, background in (("App.TFrame", BG), ("Panel.TFrame", SURFACE), ("Inset.TFrame", FIELD)):
        style.configure(name, background=background)
    for name, background, color, size, weight in (
        ("TLabel", SURFACE, INK, 10, "normal"),
        ("Muted.TLabel", BG, MUTED, 10, "normal"),
        ("PanelMuted.TLabel", SURFACE, MUTED, 10, "normal"),
        ("Heading.TLabel", BG, INK, 24, "bold"),
        ("Section.TLabel", SURFACE, INK, 12, "bold"),
        ("Eyebrow.TLabel", SURFACE, ACCENT, 9, "bold"),
        ("Metric.TLabel", SURFACE, INK, 14, "bold"),
        ("Inset.TLabel", FIELD, MUTED, 9, "normal"),
    ):
        style.configure(name, background=background, foreground=color, font=(FONT, size, weight))
    style.configure("TButton", padding=(16, 10), background=HOVER, foreground=INK, borderwidth=0, relief="flat", focusthickness=1, focuscolor=ACCENT, font=(FONT, 10))
    style.map("TButton", background=[("disabled", SURFACE), ("pressed", BORDER), ("active", "#343B2F")], foreground=[("disabled", FAINT)], bordercolor=[("focus", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_INK, font=(FONT, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", "#3A3929"), ("pressed", "#D3AA43"), ("active", ACCENT_HOVER)], foreground=[("disabled", FAINT), ("!disabled", ACCENT_INK)])
    style.configure("Danger.TButton", foreground=DANGER)
    for name in ("TEntry", "TCombobox"):
        style.configure(name, padding=9, font=(FONT, 10), fieldbackground=FIELD, background=FIELD, foreground=INK, insertcolor=ACCENT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED, selectbackground=ACCENT, selectforeground=ACCENT_INK)
        style.map(name, fieldbackground=[("disabled", SURFACE), ("readonly", FIELD)], foreground=[("disabled", FAINT), ("readonly", INK)], bordercolor=[("focus", ACCENT), ("active", "#586148")], lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)], selectbackground=[("!focus", FIELD)], selectforeground=[("!focus", INK)])
    style.configure("TCheckbutton", background=SURFACE, foreground=INK, font=(FONT, 10), indicatorsize=15, indicatorbackground=FIELD, indicatorforeground=ACCENT_INK, upperbordercolor=BORDER, lowerbordercolor=BORDER, focuscolor=ACCENT)
    style.map("TCheckbutton", background=[("active", SURFACE)], foreground=[("disabled", FAINT)], indicatorbackground=[("selected", ACCENT), ("active", HOVER)])
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD, bordercolor=FIELD, borderwidth=0, lightcolor=FIELD, darkcolor=FIELD, arrowsize=3, relief="flat")
    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=BG, borderwidth=0, lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED, arrowsize=11, width=11, relief="flat")
    style.map("Vertical.TScrollbar", background=[("active", FAINT), ("pressed", MUTED)])
    for key, value in (("background", FIELD), ("foreground", INK), ("selectBackground", ACCENT), ("selectForeground", ACCENT_INK), ("borderWidth", 0), ("font", (FONT, 10))):
        root.option_add("*TCombobox*Listbox." + key, value)
    root.option_add("*insertBackground", ACCENT)
    root.option_add("*selectBackground", ACCENT)
    root.option_add("*selectForeground", ACCENT_INK)


class Card(tk.Canvas):
    """Rounded, content-sized panel; its child frame remains ordinary ttk."""
    def __init__(self, parent, accent=False, padding=18):
        super().__init__(parent, background=BG, borderwidth=0, highlightthickness=0, height=40)
        self.accent = accent
        self.content = ttk.Frame(self, style="Panel.TFrame", padding=padding - 10)
        self.window = self.create_window(11, 11, anchor="nw", window=self.content)
        self.content.bind("<Configure>", self._content_size)
        self.bind("<Configure>", self._size)

    def _content_size(self, event):
        height = event.height + 22
        if int(self.cget("height")) != height:
            self.configure(height=height)
        self._draw(self.winfo_width(), height)

    def _size(self, event):
        self.itemconfigure(self.window, width=max(1, event.width - 22))
        self._draw(event.width, self.winfo_height())

    def _draw(self, width, height):
        if width < 24 or height < 24:
            return
        self.delete("panel")
        r = 14
        points = [1, r, 1, 1, r, 1, width-r, 1, width-1, 1, width-1, r, width-1, height-r, width-1, height-1, width-r, height-1, r, height-1, 1, height-1, 1, height-r]
        self.create_polygon(points, smooth=True, splinesteps=20, fill=SURFACE, outline="#635632" if self.accent else BORDER, width=1, tags="panel")
        self.tag_lower("panel")


class NavButton(tk.Frame):
    def __init__(self, parent, label, command, image=None):
        super().__init__(parent, background=SIDEBAR, cursor="hand2", takefocus=True, highlightthickness=0)
        self.active = False
        self.label = label
        self.marker = tk.Frame(self, background=SIDEBAR, width=3)
        self.marker.pack(side="left", fill="y", pady=10)
        self.button = tk.Label(self, text=label, image=image, compound="left", anchor="w", background=SIDEBAR, foreground=MUTED, font=(FONT, 10), padx=15, pady=13)
        self.button.pack(fill="x", expand=True)
        for widget in (self, self.marker, self.button):
            widget.bind("<Button-1>", lambda event: command())
            widget.bind("<Enter>", lambda event: self.paint(True))
            widget.bind("<Leave>", lambda event: self.paint(False))
        self.bind("<Return>", lambda event: command())
        self.bind("<space>", lambda event: command())
        self.bind("<FocusIn>", lambda event: self.paint(True))
        self.bind("<FocusOut>", lambda event: self.paint(False))

    def select(self, active):
        self.active = active
        self.paint(False)

    def paint(self, hover):
        color = ACCENT_SURFACE if self.active else HOVER if hover else SIDEBAR
        self.configure(background=color)
        self.marker.configure(background=ACCENT if self.active else color)
        self.button.configure(background=color, foreground=ACCENT if self.active else INK if hover else MUTED)


class TextArea(scrolledtext.ScrolledText):
    def __init__(self, parent, **options):
        defaults = dict(background=FIELD, foreground=INK, insertbackground=ACCENT, selectbackground=ACCENT, selectforeground=ACCENT_INK, relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, padx=14, pady=14, wrap="word")
        super().__init__(parent, **{**defaults, **options})
        self.frame.configure(background=FIELD)
        self.vbar.destroy()
        self.vbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.yview)
        self.vbar.pack(side="right", fill="y", before=self._w)
        self.configure(yscrollcommand=self.vbar.set)


def responsive_labels(parent):
    for widget in parent.winfo_children():
        if isinstance(widget, ttk.Label):
            maximum = widget.winfo_pixels(widget.cget("wraplength") or 0)
            if maximum > 0:
                def fit(event, label=widget, limit=maximum):
                    if event.width > 60:
                        width = min(limit, max(40, event.width - 24))
                        if label.winfo_pixels(label.cget("wraplength")) != width:
                            label.configure(wraplength=width)
                widget.master.bind("<Configure>", fit, add="+")
        responsive_labels(widget)
