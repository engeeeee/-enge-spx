from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import webbrowser

from . import __version__
from .brand import APP_NAME, PROJECT_URL
from .downloads import DownloadPaused
from .engine import Docker, Engine
from .nodes import fetch_subscription, normalize, parse_nodes
from .platform_ui import ASSETS, WindowInstance, install_icons, prepare_windows
from .proxy import detect_system_proxy, protocol, proxy_url, relay_config
from .state import SPXError, status_snapshot

BG, WHITE, INK, MUTED, BLUE, BORDER = "#F3F5F9", "#FFFFFF", "#17243D", "#78849A", "#3355D6", "#E6EAF2"


def size_text(value):
    return f"{value / 1024**3:.2f} GB" if value >= 1024**3 else f"{value / 1024**2:.1f} MB" if value >= 1024**2 else f"{value / 1024:.0f} KB"


class Page(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="App.TFrame")
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, style="App.TFrame", padding=(28, 8, 28, 24))
        window = self.canvas.create_window((0, 0), anchor="nw", window=self.content)
        self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))


class App:
    def __init__(self, root, store, auto_check=True):
        self.root, self.store = root, store
        self.events, self.buttons, self.nodes = queue.Queue(), [], []
        self.busy = self.cancelable = self.close_pending = False
        self.cancel = threading.Event()
        self.compatible = False
        self.runtime_ok = len(store.read("images.json", {})) == 3
        self.doctor_pending = False
        self.style()
        root.title(APP_NAME)
        root.geometry("1180x840")
        root.minsize(980, 700)
        root.configure(bg=BG)
        install_icons(root)
        settings = store.settings()
        for key, value in {"selected": "", "timezone": settings["timezone"], "context": settings["context"], "project": (settings["projects"] or [""])[-1], "relay_url": proxy_url(settings["relay"]) or "http://127.0.0.1:7890", "phase": "准备你的工作环境", "detail": "配置本机线路与落地代理，然后核对出口。", "operation": "就绪", "docker_text": "等待检测 Docker Desktop", "runtime_text": "已有环境，等待核验" if self.runtime_ok else "尚未安装运行环境", "route": "本机线路（可选） → 落地代理 → 目标服务", "ip": "—", "region": "—", "download_title": "下载预构建运行环境", "download_detail": "支持断点续传，完成后自动校验并导入 Docker。"}.items():
            setattr(self, key, tk.StringVar(value=value))
        self.relay_enabled = tk.BooleanVar(value=settings["relay"].get("enabled", False))
        self.relay_downloads = tk.BooleanVar(value=settings["relay"].get("downloads", True))
        side = tk.Frame(root, bg=WHITE, width=216, highlightbackground=BORDER, highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=WHITE)
        brand.pack(fill="x", padx=20, pady=(28, 30))
        self.pictures = {"logo": tk.PhotoImage(file=str(ASSETS / "logo-64.png")).subsample(2)}
        tk.Label(brand, image=self.pictures["logo"], bg=WHITE).pack(side="left", padx=(0, 10))
        titles = tk.Frame(brand, bg=WHITE)
        titles.pack(side="left")
        tk.Label(titles, text="ENGE SPX", fg=INK, bg=WHITE, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(titles, text="PERSONAL WORKSPACE", fg=MUTED, bg=WHITE, font=("Segoe UI", 7)).pack(anchor="w")
        self.nav, self.pages = {}, {}
        names = [("overview", "工作台"), ("connection", "连接与代理"), ("workspace", "项目工作区"), ("downloads", "下载与安装"), ("logs", "运行日志"), ("settings", "偏好设置")]
        for name, label in names:
            self.pictures[name] = tk.PhotoImage(file=str(ASSETS / (name + ".png")))
            button = tk.Button(side, text="   " + label, image=self.pictures[name], compound="left", anchor="w", borderwidth=0, bg=WHITE, fg=MUTED, activebackground="#EEF2FF", activeforeground=BLUE, font=("Segoe UI", 11), padx=14, pady=11, cursor="hand2", command=lambda n=name: self.show_page(n))
            button.pack(fill="x", padx=12, pady=3)
            self.nav[name] = button
        tk.Label(side, text="Windows Preview\nv" + __version__, fg=MUTED, bg=WHITE, justify="left", font=("Segoe UI", 9)).pack(side="bottom", anchor="w", padx=24, pady=26)
        main = ttk.Frame(root, style="App.TFrame")
        main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main, style="App.TFrame", padding=(28, 26, 28, 18))
        top.pack(fill="x")
        self.heading = tk.StringVar(value="工作台")
        ttk.Label(top, textvariable=self.heading, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(top, text="一次配置，继续手边的项目。", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        holder = ttk.Frame(main, style="App.TFrame")
        holder.pack(fill="both", expand=True)
        for name, label in names:
            self.pages[name] = Page(holder)
        self.build_overview(self.pages["overview"].content)
        self.build_connection(self.pages["connection"].content)
        self.build_workspace(self.pages["workspace"].content)
        self.build_downloads(self.pages["downloads"].content)
        self.build_logs(self.pages["logs"].content)
        self.build_settings(self.pages["settings"].content)
        footer = ttk.Frame(main, style="App.TFrame", padding=(28, 10, 28, 14))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.operation, style="Muted.TLabel", wraplength=840).pack(anchor="w")
        self.refresh_nodes()
        self.show_page("overview")
        root.bind("<MouseWheel>", self.scroll_page, add="+")
        root.bind("<Button-4>", self.scroll_page, add="+")
        root.bind("<Button-5>", self.scroll_page, add="+")
        self.poll()
        root.protocol("WM_DELETE_WINDOW", self.close)
        if auto_check:
            root.after(500, self.check_docker)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG)
        style.configure("Panel.TFrame", background=WHITE)
        for name, background, color, size, weight in [("TLabel", WHITE, INK, 10, "normal"), ("Muted.TLabel", BG, MUTED, 10, "normal"), ("PanelMuted.TLabel", WHITE, MUTED, 10, "normal"), ("Heading.TLabel", BG, INK, 23, "bold"), ("Section.TLabel", WHITE, INK, 12, "bold")]:
            style.configure(name, background=background, foreground=color, font=("Segoe UI", size, weight))
        style.configure("TButton", padding=(15, 9), background="#F0F3F8", foreground=INK, borderwidth=0, font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#E4EAF5")], foreground=[("disabled", "#A4ADBD")])
        style.configure("Accent.TButton", background=BLUE, foreground=WHITE)
        style.map("Accent.TButton", background=[("active", "#2948BD"), ("disabled", "#CBD4ED")], foreground=[("disabled", "#F6F8FF")])
        style.configure("TEntry", padding=8, bordercolor=BORDER)
        style.configure("TCombobox", padding=7, bordercolor=BORDER)
        style.configure("TCheckbutton", background=WHITE, font=("Segoe UI", 10))
        style.configure("Horizontal.TProgressbar", background=BLUE, troughcolor="#E9EDF6", borderwidth=0, thickness=7)

    def card(self, parent, title=None, caption=None):
        border = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        border.pack(fill="x", pady=(0, 16))
        frame = ttk.Frame(border, style="Panel.TFrame", padding=20)
        frame.pack(fill="both", expand=True)
        if title:
            ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w")
        if caption:
            ttk.Label(frame, text=caption, style="PanelMuted.TLabel", wraplength=780).pack(anchor="w", pady=(7, 14))
        return frame

    def row(self, parent):
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x")
        return frame

    def button(self, parent, text, command, accent=False, ready=False):
        button = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton")
        self.buttons.append((button, ready))
        return button

    def build_overview(self, parent):
        card = self.card(parent)
        self.dot = tk.Label(card, text="●", fg=MUTED, bg=WHITE, font=("Segoe UI", 13))
        self.dot.pack(anchor="w")
        ttk.Label(card, textvariable=self.phase, font=("Segoe UI", 19, "bold")).pack(anchor="w", pady=(6, 8))
        ttk.Label(card, textvariable=self.detail, style="PanelMuted.TLabel", wraplength=780).pack(anchor="w")
        self.next_button = self.button(card, "准备运行环境", self.next_step, True)
        self.next_button.pack(anchor="w", pady=(18, 0))
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill="x", pady=(0, 16))
        for column, (label, variable) in enumerate([("落地出口 IP", self.ip), ("预计地区", self.region), ("环境时区", self.timezone)]):
            row.columnconfigure(column, weight=1, uniform="stats")
            pane = ttk.Frame(row, style="Panel.TFrame", padding=16)
            pane.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
            ttk.Label(pane, text=label, style="PanelMuted.TLabel").pack(anchor="w")
            ttk.Label(pane, textvariable=variable, font=("Segoe UI", 11, "bold"), wraplength=225).pack(anchor="w", pady=(9, 0))
        card = self.card(parent, "你的连接路径")
        ttk.Label(card, textvariable=self.route, wraplength=780).pack(anchor="w", pady=(12, 8))
        ttk.Label(card, text="最终出口由落地代理提供，本机线路只负责前置中转。", style="PanelMuted.TLabel").pack(anchor="w")
        card = self.card(parent, "继续工作", "选择已有项目，账号与会话会保留。")
        self.button(card, "打开项目工作区  →", lambda: self.show_page("workspace")).pack(anchor="w")

    def build_connection(self, parent):
        card = self.card(parent, "落地代理", "添加 SOCKS5、HTTP、HTTPS 代理，或导入已有协议的节点配置。")
        row = self.row(card)
        self.node_box = ttk.Combobox(row, textvariable=self.selected, state="readonly")
        self.node_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.button(row, "添加代理", self.proxy_dialog, True).pack(side="left")
        self.button(card, "批量导入链接 / 订阅 / 配置", self.import_dialog).pack(anchor="w", pady=(12, 0))
        card = self.card(parent, "本机线路中转", "已有线路客户端时启用：本机线路 → 落地代理 → 目标服务。无需开放到局域网。")
        ttk.Checkbutton(card, text="通过本机代理连接落地", variable=self.relay_enabled).pack(anchor="w", pady=(0, 12))
        row = self.row(card)
        ttk.Entry(row, textvariable=self.relay_url).pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.button(row, "读取系统代理", self.read_system_proxy).pack(side="left")
        ttk.Label(card, text="例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080", style="PanelMuted.TLabel").pack(anchor="w", pady=(8, 12))
        ttk.Checkbutton(card, text="下载运行环境时也使用本机线路", variable=self.relay_downloads).pack(anchor="w")
        card = self.card(parent, "核对并启用", "检查会停止本环境中的工作，请先保存项目，再核对实际落地出口。")
        ttk.Label(card, textvariable=self.route, wraplength=780).pack(anchor="w", pady=(0, 12))
        row = self.row(card)
        for text, action in [("保存设置", self.save_settings), ("检查连接", self.check)]:
            self.button(row, text, action).pack(side="left", padx=(0, 8))
        self.confirm_button = self.button(row, "核对并确认", self.confirm, True)
        self.confirm_button.pack(side="left", padx=(0, 8))
        self.button(row, "停止环境", lambda: self.run(lambda e: e.stop())).pack(side="left")

    def build_workspace(self, parent):
        card = self.card(parent, "选择项目", "工具直接读写所选文件夹，请使用正常的版本管理。")
        row = self.row(card)
        self.project_box = ttk.Combobox(row, textvariable=self.project, values=self.store.settings()["projects"])
        self.project_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.button(row, "选择文件夹", self.choose_project).pack(side="left")
        card = self.card(parent, "打开你的工具", "连接确认后即可启动。各项目使用不同的工作路径，共享工具账号。")
        row = self.row(card)
        for label, tool in [("Claude Code", "claude"), ("Codex", "codex"), ("Linux 终端", "shell")]:
            self.button(row, label + "  ↗", lambda t=tool: self.open_terminal(t), accent=tool == "claude", ready=True).pack(side="left", padx=(0, 10))
        card = self.card(parent, "账号与共享浏览器", "授权页面在共享 Chromium 中打开；关闭远程显示网页会保留浏览器。")
        row = self.row(card)
        for label, tool in [("登录 Claude Code", "login-claude"), ("登录 Codex", "login-codex")]:
            self.button(row, label, lambda t=tool: self.open_terminal(t), ready=True).pack(side="left", padx=(0, 10))
        self.button(card, "打开共享 Chromium", self.open_browser, ready=True).pack(anchor="w", pady=(14, 0))

    def build_downloads(self, parent):
        card = self.card(parent, "Docker Desktop", "保持 Docker Desktop 运行，使用 WSL 2 / Linux containers。")
        ttk.Label(card, textvariable=self.docker_text).pack(anchor="w", pady=(0, 12))
        row = self.row(card)
        for text, action in [("重新检测", self.check_docker), ("启动 Docker Desktop", self.start_docker), ("下载 Docker", lambda: webbrowser.open("https://docs.docker.com/desktop/setup/install/windows-install/"))]:
            self.button(row, text, action).pack(side="left", padx=(0, 8))
        card = self.card(parent, "运行环境", "直接获取预构建环境，无需在本机逐项下载和构建工具。")
        ttk.Label(card, textvariable=self.runtime_text, style="PanelMuted.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(card, textvariable=self.download_title, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.progressbar = ttk.Progressbar(card, maximum=100)
        self.progressbar.pack(fill="x", pady=(16, 10))
        ttk.Label(card, textvariable=self.download_detail, style="PanelMuted.TLabel", wraplength=780).pack(anchor="w")
        row = self.row(card)
        self.button(row, "下载并安装 / 继续下载", self.install_runtime, True).pack(side="left", pady=(18, 0), padx=(0, 10))
        self.pause_button = ttk.Button(row, text="暂停", command=self.pause, state="disabled")
        self.pause_button.pack(side="left", pady=(18, 0))
        card = self.card(parent, "高级方式", "开发者可从源码构建；已完成的构建缓存会保留。")
        self.button(card, "从源码构建（较慢）", lambda: self.install_runtime(source=True)).pack(anchor="w")

    def build_logs(self, parent):
        card = self.card(parent, "运行日志", "详细安装输出也保存在数据目录中的 build.log。")
        self.log_view = scrolledtext.ScrolledText(card, height=22, font=("Consolas", 10), bg="#162238", fg="#DCE5F5", relief="flat", state="disabled", padx=14, pady=14)
        self.log_view.pack(fill="both", expand=True)
        self.button(card, "打开数据目录", self.open_data).pack(anchor="w", pady=(12, 0))

    def build_settings(self, parent):
        card = self.card(parent, "环境设置", "已建立的环境固定时区；其他时区请使用独立数据目录。")
        for label, variable in [("IANA 时区", self.timezone), ("本机 Docker 上下文", self.context)]:
            ttk.Label(card, text=label).pack(anchor="w", pady=(5, 6))
            ttk.Entry(card, textvariable=variable, width=45).pack(anchor="w", pady=(0, 12))
        self.button(card, "保存设置", self.save_settings, True).pack(anchor="w")
        card = self.card(parent, "数据与后台运行")
        ttk.Label(card, text=str(self.store.home), wraplength=780).pack(anchor="w", pady=(10, 8))
        ttk.Label(card, text="配置保存在本机；工具账号、会话和浏览器资料位于 Docker 数据卷。\n关闭窗口后，已确认的环境与监测进程继续运行；退出工作请点击“停止环境”。", style="PanelMuted.TLabel", wraplength=780).pack(anchor="w")
        self.button(card, "打开数据目录", self.open_data).pack(anchor="w", pady=(14, 0))
        card = self.card(parent, "关于 ENGE SPX")
        ttk.Label(card, text="Windows Preview " + __version__).pack(anchor="w", pady=(10, 12))
        self.button(card, "更新与使用说明", lambda: webbrowser.open(PROJECT_URL + "/releases")).pack(anchor="w")

    def show_page(self, name):
        for key, page in self.pages.items():
            page.pack_forget()
            self.nav[key].configure(bg="#EEF2FF" if key == name else WHITE, fg=BLUE if key == name else MUTED)
        self.pages[name].pack(fill="both", expand=True)
        self.heading.set(self.nav[name].cget("text").strip())
        self.page_name = name

    def scroll_page(self, event):
        if isinstance(event.widget, (tk.Text, tk.Listbox, ttk.Combobox)):
            return
        canvas = self.pages[self.page_name].canvas
        if canvas.yview() != (0.0, 1.0):
            step = -1 if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0 else 1
            canvas.yview_scroll(step * 3, "units")

    def add_log(self, value):
        self.log_view.configure(state="normal")
        self.log_view.insert("end", datetime.now().strftime("%H:%M:%S  ") + str(value) + "\n")
        if int(self.log_view.index("end-1c").split(".")[0]) > 1200:
            self.log_view.delete("1.0", "200.0")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def run(self, action, done=None, cancelable=False):
        if self.busy:
            return
        self.busy, self.cancelable = True, cancelable
        self.cancel.clear()
        self.operation.set("正在处理…")
        def worker():
            try:
                engine = Engine(self.store, lambda text: self.events.put(("log", text)))
                result = action(engine)
                state = self.store.read("runtime.json", {})
                compatible = state.get("phase") != "ready" or state.get("policy") == engine.policy()
                self.events.put(("done", (result, done, compatible)))
            except DownloadPaused as error:
                self.events.put(("paused", str(error)))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def refresh_nodes(self):
        self.nodes = self.store.read("nodes.json", [])
        self.node_box["values"] = [f"{protocol(n)}  ·  {n['label']}" for n in self.nodes]
        index = next((i for i, n in enumerate(self.nodes) if n["id"] == self.store.settings()["selected"]), 0)
        if self.nodes:
            self.node_box.current(index)

    def node_id(self):
        index = self.node_box.current()
        return self.nodes[index]["id"] if 0 <= index < len(self.nodes) else ""

    def captured_settings(self):
        try:
            return self.node_id(), self.timezone.get().strip(), self.context.get().strip(), relay_config(self.relay_enabled.get(), self.relay_url.get(), self.relay_downloads.get())
        except SPXError as error:
            messagebox.showinfo("检查本机线路地址", str(error), parent=self.root)
            return None

    def settings_match(self):
        saved = self.store.settings()
        try:
            relay = relay_config(self.relay_enabled.get(), self.relay_url.get(), self.relay_downloads.get())
            return (self.node_id(), self.timezone.get().strip(), self.context.get().strip(), {k: v for k, v in relay.items() if k != "downloads"}) == (saved["selected"], saved["timezone"], saved["context"], {k: v for k, v in saved["relay"].items() if k != "downloads"})
        except SPXError:
            return False

    def save_settings(self):
        values = self.captured_settings()
        if values:
            self.run(lambda e: e.save_settings(*values))

    def consent_stop(self):
        return status_snapshot(self.store)["phase"] != "ready" or messagebox.askyesno("更新连接", "此操作会停止当前环境，请先保存工作。继续？", parent=self.root)

    def check(self):
        if not self.consent_stop():
            return
        values = self.captured_settings()
        if values:
            def action(engine):
                engine.save_settings(*values)
                return Engine(self.store, engine.log).check()
            self.run(action)

    def confirm(self):
        if self.settings_match() and messagebox.askyesno("核对落地出口", f"出口 IP：{self.ip.get()}\n预计地区：{self.region.get()}\n环境时区：{self.timezone.get()}\n\n确认后启用环境？", parent=self.root):
            self.run(lambda e: e.confirm())

    def choose_project(self):
        value = filedialog.askdirectory(title="选择项目目录", parent=self.root)
        if value:
            self.project.set(value)

    def open_terminal(self, tool):
        if not self.settings_match():
            self.show_page("connection")
            return
        if not self.project.get().strip():
            self.choose_project()
        path = self.project.get().strip()
        if path:
            self.run(lambda e: e.terminal(path, tool))

    def open_browser(self):
        if self.settings_match():
            self.run(lambda e: e.browser())

    def read_system_proxy(self):
        try:
            self.relay_url.set(detect_system_proxy())
            self.relay_enabled.set(True)
            self.operation.set("已读取本机代理，请保存后检查连接。")
        except SPXError as error:
            messagebox.showinfo("手动填写本机代理", str(error), parent=self.root)

    def proxy_dialog(self):
        if not self.consent_stop():
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("添加落地代理")
        dialog.geometry("520x490")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, style="Panel.TFrame", padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="添加落地代理", style="Section.TLabel").pack(anchor="w", pady=(0, 16))
        variables = {k: tk.StringVar(value=v) for k, v in {"type": "SOCKS5", "server": "", "port": "1080", "username": "", "password": "", "name": ""}.items()}
        for label, key in [("协议", "type"), ("服务器地址", "server"), ("端口", "port"), ("用户名（可选）", "username"), ("密码（可选）", "password"), ("名称（可选）", "name")]:
            row = self.row(frame)
            row.pack_configure(pady=5)
            ttk.Label(row, text=label, width=15).pack(side="left")
            if key == "type":
                entry = ttk.Combobox(row, textvariable=variables[key], values=["SOCKS5", "HTTP", "HTTPS"], state="readonly")
                entry.bind("<<ComboboxSelected>>", lambda e: variables["port"].set({"SOCKS5": "1080", "HTTP": "80", "HTTPS": "443"}[variables["type"].get()]))
            else:
                entry = ttk.Entry(row, textvariable=variables[key], show="•" if key == "password" else "")
            entry.pack(side="left", fill="x", expand=True)
        def save():
            try:
                values = {k: v.get() for k, v in variables.items()}
                node = normalize({"type": values["type"].lower(), "server": values["server"], "server_port": values["port"], "username": values["username"], "password": values["password"]}, values["name"])
            except (ValueError, TypeError):
                messagebox.showinfo("检查代理信息", "请检查服务器、端口及认证信息。", parent=dialog)
                return
            nodes = [node, *[n for n in self.store.read("nodes.json", []) if n["id"] != node["id"]]]
            dialog.destroy()
            self.run(lambda e: e.save_nodes(nodes), lambda result: self.refresh_nodes())
        ttk.Button(frame, text="保存落地代理", style="Accent.TButton", command=save).pack(anchor="e", pady=(18, 0))

    def import_dialog(self):
        if not self.consent_stop():
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("导入落地代理")
        dialog.geometry("680x470")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, style="Panel.TFrame", padding=22)
        frame.pack(fill="both", expand=True)
        mode = tk.StringVar(value="代理链接 / JSON / Clash")
        ttk.Combobox(frame, textvariable=mode, values=["代理链接 / JSON / Clash", "订阅地址（HTTPS）"], state="readonly").pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="HTTPS 代理使用第一项；下载订阅需明确选择第二项。", style="PanelMuted.TLabel").pack(anchor="w", pady=(0, 10))
        entry = scrolledtext.ScrolledText(frame, height=11, font=("Consolas", 10))
        entry.pack(fill="both", expand=True)
        def file():
            path = filedialog.askopenfilename(parent=dialog)
            if path:
                try:
                    if Path(path).stat().st_size > 2 * 1024**2:
                        raise ValueError()
                    entry.delete("1.0", "end")
                    entry.insert("1.0", Path(path).read_text(encoding="utf-8-sig"))
                    mode.set("代理链接 / JSON / Clash")
                except (OSError, ValueError):
                    messagebox.showinfo("读取失败", "请选择小于 2 MiB 的 UTF-8 配置文件。", parent=dialog)
        def accept():
            text, subscription = entry.get("1.0", "end").strip(), mode.get() == "订阅地址（HTTPS）"
            dialog.destroy()
            def action(engine):
                nodes, warnings = parse_nodes(fetch_subscription(text) if subscription else text)
                engine.save_nodes(nodes)
                return len(nodes), warnings
            def done(result):
                self.refresh_nodes()
                self.operation.set(f"已导入 {result[0]} 个落地节点。")
                if result[1]:
                    messagebox.showinfo("已跳过部分节点", "\n".join(result[1][:10]), parent=self.root)
            self.run(action, done)
        row = self.row(frame)
        row.pack_configure(pady=(14, 0))
        ttk.Button(row, text="选择配置文件", command=file).pack(side="left")
        ttk.Button(row, text="导入", command=accept, style="Accent.TButton").pack(side="right")

    def install_runtime(self, source=False):
        values = self.captured_settings()
        if not values:
            return
        self.show_page("downloads")
        def action(engine):
            engine.save_settings(*values)
            current = Engine(self.store, engine.log)
            progress = lambda value: self.events.put(("progress", value))
            return current.install(progress, self.cancel) if source else current.install_prebuilt(progress, self.cancel)
        def done(result):
            self.runtime_ok = True
            self.download_title.set("安装完成")
            self.download_detail.set("现在可以配置落地代理并核对连接。")
            self.check_docker()
        self.run(action, done, cancelable=True)

    def pause(self):
        self.cancel.set()
        self.download_detail.set("正在暂停，已完成部分会保留…")

    def check_docker(self):
        if self.doctor_pending:
            return
        self.doctor_pending = True
        self.docker_text.set("正在检测 Docker Desktop…")
        def worker():
            try:
                engine = Engine(self.store)
                info = engine.doctor()
                try:
                    engine.image_ids()
                    installed = True
                except SPXError:
                    installed = False
                state = self.store.read("runtime.json", {})
                valid = state.get("phase") != "ready" or state.get("policy") == engine.policy()
                self.events.put(("docker", (info, installed, valid)))
            except Exception as error:
                self.events.put(("docker_error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def start_docker(self):
        path = Docker.desktop_app()
        if not path:
            self.docker_text.set("未找到 Docker Desktop，请先点击“下载 Docker”。")
            return
        import subprocess
        subprocess.Popen([str(path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.docker_text.set("Docker Desktop 正在启动，稍后可重新检测。")
        self.root.after(5000, self.check_docker)

    def open_data(self):
        if os.name == "nt":
            os.startfile(str(self.store.home))
        else:
            self.operation.set(str(self.store.home))

    def next_step(self):
        state = status_snapshot(self.store)
        if not self.runtime_ok:
            self.show_page("downloads")
        elif not self.nodes:
            self.show_page("connection")
            self.proxy_dialog()
        elif state["phase"] == "ready" and self.settings_match() and self.compatible:
            self.show_page("workspace")
        elif state["phase"] == "review" and self.settings_match():
            self.confirm()
        else:
            self.show_page("connection")
            self.check()

    def update_progress(self, value):
        stage = value.get("stage")
        self.progressbar.stop()
        self.download_title.set({"manifest": "获取运行环境信息", "download": "正在下载运行环境", "retry": "正在重试连接", "verify": "校验下载文件", "import": "导入运行环境", "build": "从源码构建", "done": "安装完成"}.get(stage, "正在处理"))
        if stage == "download":
            self.progressbar.configure(mode="determinate", value=value["bytes"] / value["total"] * 100)
            eta = value.get("eta")
            suffix = f"  ·  约 {int(eta // 60)} 分 {int(eta % 60)} 秒" if eta else ""
            self.download_detail.set(f"{size_text(value['bytes'])} / {size_text(value['total'])}  ·  {size_text(value['speed'])}/s" + suffix)
        elif stage == "done":
            self.progressbar.configure(mode="determinate", value=100)
        else:
            self.progressbar.configure(mode="indeterminate")
            self.progressbar.start(12)
            self.download_detail.set({"manifest": "正在通过所选下载线路读取文件信息…", "verify": "下载已完成，正在核对 SHA-256…", "import": "校验通过，正在交给 Docker 导入…", "build": "详细构建进度见运行日志。", "retry": "进度已保留，正在重新连接…"}.get(stage, "正在处理…"))

    def render(self):
        state = status_snapshot(self.store)
        matching = self.settings_match()
        ready = state["phase"] == "ready" and matching and self.compatible and state["guard_age"] <= 100
        title = {"stopped": "环境已停止", "checking": "正在检查落地出口", "review": "请核对落地出口", "ready": "连接已确认，开始工作"}.get(state["phase"], "等待配置")
        detail = state.get("reason") or ("后台持续监测连接，线路或出口变化后会停止本环境。" if ready else "检查落地出口后，再确认启用环境。")
        if not self.runtime_ok:
            title, detail = "准备你的工作环境", "先下载运行环境，再配置本机线路和落地代理。"
        elif not self.nodes:
            title, detail = "添加你的落地代理", "已有线路节点时，可以启用本机前置中转。"
        elif state["phase"] in ("ready", "review") and not matching:
            title, detail = "代理设置已更改", "当前选择需要重新检查和确认。"
        elif state["phase"] == "ready" and not ready:
            title, detail = "已有连接需要重新核验", "请检查当前环境，再核对落地出口。"
        self.phase.set(title)
        self.detail.set(detail)
        self.dot.configure(fg="#16866C" if ready else "#D49A33" if state["phase"] == "review" else MUTED)
        evidence = state.get("evidence") or {}
        self.ip.set(evidence.get("ip", "—"))
        self.region.set(evidence.get("country", "—") + " / " + evidence.get("city", "—"))
        index = self.node_box.current()
        if 0 <= index < len(self.nodes):
            node = self.nodes[index]
            value = node["outbound"]
            self.route.set(("本机线路 → " if self.relay_enabled.get() else "") + f"{protocol(node)} 落地  {value['server']}:{value['server_port']}  →  目标服务")
        for button, needs_ready in self.buttons:
            button.configure(state="disabled" if self.busy or needs_ready and not ready else "normal")
        self.confirm_button.configure(state="normal" if not self.busy and state["phase"] == "review" and matching else "disabled")
        self.pause_button.configure(state="normal" if self.busy and self.cancelable and not self.cancel.is_set() else "disabled")
        self.next_button.configure(text="准备运行环境" if not self.runtime_ok else "添加落地代理" if not self.nodes else "打开项目工作区" if ready else "核对并确认" if state["phase"] == "review" and matching else "检查当前连接")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.add_log(value)
                elif kind == "progress":
                    self.update_progress(value)
                elif kind in ("docker", "docker_error"):
                    self.doctor_pending = False
                    if kind == "docker":
                        info, self.runtime_ok, self.compatible = value
                        self.docker_text.set(f"Docker 已就绪  ·  {info['docker']}  ·  {info['architecture']}")
                        self.runtime_text.set("运行环境已核验" if self.runtime_ok else "需要安装或更新运行环境")
                    else:
                        self.docker_text.set("Docker 尚未就绪，请安装或启动后重新检测。")
                        self.add_log(value)
                else:
                    self.busy = False
                    self.progressbar.stop()
                    if kind == "done":
                        result, callback, self.compatible = value
                        self.operation.set("操作完成")
                        if callback:
                            callback(result)
                    elif kind == "paused":
                        self.download_title.set("已暂停")
                        self.download_detail.set(value)
                        self.operation.set(value)
                    else:
                        self.operation.set("操作未完成：" + str(value)[:160])
                        self.add_log(value)
                        if self.cancelable:
                            self.download_title.set("可以重试")
                            self.download_detail.set(value)
                        else:
                            messagebox.showerror("操作未完成", value, parent=self.root)
                    if self.close_pending:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        try:
            self.render()
        except Exception:
            self.phase.set("状态暂不可用，请查看运行日志")
        self.root.after(250, self.poll)

    def close(self):
        if self.busy:
            if self.cancelable and messagebox.askyesno("暂停并退出", "暂停当前操作并退出？已下载的内容会保留。", parent=self.root):
                self.close_pending = True
                self.pause()
            elif not self.cancelable:
                messagebox.showinfo("操作进行中", "请等待当前操作安全完成后再退出。", parent=self.root)
            return
        self.root.destroy()


def launch(store, smoke=False):
    started = time.perf_counter()
    prepare_windows()
    instance = WindowInstance(store.home, legacy=store.legacy)
    if not instance.acquire():
        return
    root = tk.Tk()
    root.withdraw()
    try:
        App(root, store, auto_check=not smoke)
        instance.register(root)
        root.after_idle(root.deiconify)
        if smoke:
            def painted():
                root.update_idletasks()
                store.write("ui-smoke.json", {"app": root.title(), "first_paint_ms": round((time.perf_counter() - started) * 1000), "version": __version__, "icons": True})
                root.after(400, root.destroy)
            root.after(100, painted)
        root.mainloop()
    finally:
        instance.close()
