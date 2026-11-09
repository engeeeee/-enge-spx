"""Desktop state and bounded worker delivery, independent of widget layouts."""
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading
import time
import webbrowser

from PySide6.QtCore import QObject, QTimer, Signal

from .. import terminal
from ..brand import PROJECT_URL
from ..downloads import DownloadPaused
from ..engine import Engine
from ..gui_diagnostics import log
from ..line_security import LINE_MODES, v2ray_rules
from ..nodes import fetch_subscription, normalize, parse_nodes
from ..proxy import detect_system_proxy, download_proxy, protocol, proxy_url, relay_config, route_config
from ..startup import DOCKER_INSTALL_URL, StartupIssue, diagnostics, prepare_workspace
from ..state import SPXError, Store, atomic_json, status_snapshot
from ..storage import desktop_storage, plan_migration, prepare_docker_move, verify_docker_move


def size_text(value):
    return f"{value / 1024**3:.2f} GB" if value >= 1024**3 else f"{value / 1024**2:.1f} MB" if value >= 1024**2 else f"{value / 1024:.0f} KB"


class Value(QObject):
    changed = Signal(object)

    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        if value != self.value:
            self.value = value
            self.changed.emit(value)


class Controller(QObject):
    changed = Signal(object)
    nodes_changed = Signal()
    logs_added = Signal(str)
    notice = Signal(str, str, bool)
    page_requested = Signal(str)
    proxy_requested = Signal()
    close_requested = Signal()
    activation_requested = Signal()

    def __init__(self, store, report=None, on_relocated=None):
        super().__init__()
        self.store, self.report, self.on_relocated = store, report, on_relocated
        self.ask = lambda title, text: False
        self.busy = self.cancelable = self.close_pending = False
        self.compatible = self.docker_ready = self.startup_active = False
        self.desktop_launch_pending = False
        self.runtime_ok = len(store.read("images.json", {})) == 3
        self.startup_error = None
        self.last_docker_info = None
        self.events = queue.SimpleQueue()
        self.cancel = threading.Event()
        self.log_lines = []
        self.view = {}
        settings = store.settings()
        relay, term = settings["relay"], terminal.validate(settings["terminal"])
        defaults = {
            "selected": settings["selected"], "line_selected": relay.get("line_id", ""),
            "timezone": settings["timezone"], "context": settings["context"],
            "project": (settings["projects"] or [""])[-1], "relay_enabled": relay.get("enabled", False),
            "relay_url": proxy_url(relay) or "", "relay_downloads": relay.get("downloads", True),
            "line_mode": relay.get("mode", "local" if relay.get("enabled") else "managed"),
            "line_server_ip": relay.get("server_ip", ""), "line_expected_ip": relay.get("expected_ip", ""),
            "auto_start_docker": settings.get("auto_start_docker", True),
            "terminal_kind": term["kind"], "terminal_exe": term["executable"], "terminal_args": term["arguments"],
            "terminal_status": "工作区、Linux 终端和登录窗口使用相同的终端设置。",
            "data_location": str(store.home), "data_target": "D:\\ENGE-SPX\\data" if os.name == "nt" and Path("D:/").exists() else "",
            "docker_target": store.read("docker-move.json", {}).get("target", "D:\\DockerData" if os.name == "nt" and Path("D:/").exists() else ""),
            "docker_location": "检测后显示 Docker 数据盘位置。", "storage_status": "配置、日志和下载缓存可迁移到自选目录。",
            "docker_move_status": "Docker Desktop 负责实际迁移，完成后回到这里核验。",
            "operation": "就绪", "startup_title": "准备你的工作环境", "startup_detail": "自动准备 Docker 与运行环境，再核对代理出口。",
            "docker_text": "尚未检测 Docker", "runtime_text": "等待核验已有环境" if self.runtime_ok else "尚未安装运行环境",
            "download_title": "获取运行环境", "download_detail": "支持暂停与断点续传，导入前校验完整性。",
            "download_progress": 0, "startup_progress": 0, "storage_progress": 0,
        }
        self.values = {name: Value(value, self) for name, value in defaults.items()}
        for name, value in self.values.items():
            setattr(self, name, value)
        self.steps = ["等待检测", "等待核验", "等待配置", "由你确认"]
        for name in ("selected", "line_selected", "timezone", "context", "relay_enabled", "relay_url", "relay_downloads", "line_mode", "line_server_ip", "line_expected_ip"):
            self.values[name].changed.connect(lambda unused: self.schedule_refresh())
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(40)
        self.refresh_timer.timeout.connect(self.refresh)
        self.delivery = QTimer(self)
        self.delivery.setInterval(40)
        self.delivery.timeout.connect(self.drain)
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1500)
        self.status_timer.timeout.connect(self.refresh)
        self.status_timer.start()
        self.refresh_nodes()

    def schedule_refresh(self):
        self.refresh_timer.start()

    def notify(self, title, text, error=False):
        self.notice.emit(title, str(text), error)

    def refresh_nodes(self):
        self.nodes = self.store.read("nodes.json", [])
        identifiers = {node["id"] for node in self.nodes}
        if self.selected.get() not in identifiers:
            saved = self.store.settings()["selected"]
            self.selected.set(saved if saved in identifiers else self.nodes[0]["id"] if self.nodes else "")
        if self.line_selected.get() not in identifiers:
            self.line_selected.set("")
        self.nodes_changed.emit()
        self.refresh()

    def captured_relay(self):
        return relay_config(self.relay_enabled.get(), self.relay_url.get(), self.relay_downloads.get(), self.line_mode.get(), self.line_selected.get(), self.line_server_ip.get(), self.line_expected_ip.get())

    def captured_settings(self):
        return self.selected.get(), self.timezone.get().strip(), self.context.get().strip(), self.captured_relay()

    def settings_match(self):
        saved = self.store.settings()
        try:
            selected, timezone, context, relay = self.captured_settings()
            return (selected, timezone, context, route_config(relay)) == (saved["selected"], saved["timezone"], saved["context"], route_config(saved["relay"]))
        except SPXError:
            return False

    def run(self, action, done=None, cancelable=False):
        if self.busy:
            return False
        self.busy, self.cancelable = True, cancelable
        self.cancel.clear()
        self.operation.set("正在处理…")
        self.refresh()

        def worker():
            try:
                engine = Engine(self.store, lambda text: self.events.put(("log", text)))
                result = action(engine)
                state = self.store.read("runtime.json", {})
                compatible = state.get("phase") != "ready" or state.get("policy") == engine.policy()
                self.events.put(("done", (result, done, compatible)))
            except DownloadPaused as error:
                self.events.put(("paused", str(error)))
            except StartupIssue as error:
                self.events.put(("startup_error", (error.code, str(error))))
            except Exception as error:
                if self.report:
                    self.report.capture("gui-worker-error", type(error), error, error.__traceback__)
                self.events.put(("error", str(error)))

        self.delivery.start()
        threading.Thread(target=worker, name="spx-operation", daemon=True).start()
        return True

    def drain(self):
        lines, progress, changed = [], None, False
        deadline = time.perf_counter() + .008
        for _ in range(128):
            if time.perf_counter() > deadline:
                break
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                lines.append(datetime.now().strftime("%H:%M:%S  ") + str(value))
            elif kind == "progress":
                progress = value
            elif kind == "stage":
                self.update_stage(value)
            elif kind == "storage":
                self.storage_status.set(value["message"])
                if value.get("total"):
                    self.storage_progress.set(min(95, value["bytes"] / value["total"] * 95))
            else:
                self.busy = self.cancelable = False
                self.startup_progress.set(max(0, self.startup_progress.get()))
                if kind == "done":
                    result, done, self.compatible = value
                    self.operation.set("操作完成")
                    if done:
                        done(result)
                else:
                    self.startup_active = False
                    self.download_progress.set(max(0, self.download_progress.get()))
                    if kind == "startup_error":
                        self.startup_error, value = value
                        self.docker_ready = False
                        self.startup_title.set("需要完成 Docker 准备")
                        self.docker_text.set(value)
                    elif kind == "paused":
                        self.startup_title.set("准备已取消")
                        self.download_title.set("已暂停，可继续")
                    else:
                        self.startup_title.set("操作未完成，可以重试")
                        self.notify("操作未完成", value, True)
                    self.operation.set(value)
                    self.startup_detail.set(value)
                    self.download_detail.set(value)
                    lines.append(str(value))
                if self.close_pending:
                    self.close_requested.emit()
            changed = True
        if progress:
            self.update_progress(progress)
        if lines:
            self.log_lines.extend(lines)
            self.log_lines = self.log_lines[-1200:]
            self.logs_added.emit("\n".join(lines))
        if changed:
            self.refresh()
        if not self.busy and self.events.empty():
            self.delivery.stop()

    def preparation_progress(self, value):
        stage = value.get("stage")
        if stage in ("manifest", "download", "retry", "verify", "import", "build", "done"):
            self.events.put(("progress", value))
        self.events.put(("stage", value))

    def update_stage(self, value):
        stage = value.get("stage")
        log.info("gui-preparation-stage stage=%s", stage)
        titles = {"docker_check": "正在检查 Docker", "docker_start": "正在启动 Docker Desktop", "docker_wait": "等待 Linux 引擎就绪", "docker_ready": "Docker 已就绪", "runtime_check": "核验已有运行环境", "runtime_install": "准备运行环境", "configure": "环境已准备好", "connection_check": "检查线路与落地", "review": "请核对实际出口", "ready": "工作环境已就绪"}
        self.startup_title.set(titles.get(stage, self.download_title.get()))
        self.startup_detail.set(value.get("message", self.download_detail.get()))
        self.operation.set(self.startup_title.get())
        if stage == "docker_start":
            self.desktop_launch_pending = True
        if stage in ("docker_check", "docker_start", "docker_wait"):
            self.steps[0] = "启动中" if stage != "docker_check" else "检测中"
            self.startup_progress.set(-1)
        elif stage == "docker_ready":
            self.steps[0] = "已就绪"
            self.docker_ready = True
            if self.desktop_launch_pending:
                self.desktop_launch_pending = False
                self.activation_requested.emit()
                log.info("gui-restored-after-desktop")
        elif stage in ("runtime_check", "runtime_install", "manifest", "download", "retry", "verify", "import", "build"):
            self.steps[1] = "核验中" if stage == "runtime_check" else "准备中"
        elif stage in ("done", "configure", "connection_check", "review", "ready"):
            self.steps[1] = "已核验"
            if stage == "configure":
                self.steps[2] = "等待添加节点"
            elif stage == "connection_check":
                self.steps[2] = "检查中"
            elif stage in ("review", "ready"):
                self.steps[2], self.steps[3] = "检查通过", "已确认" if stage == "ready" else "等待你确认"

    def update_progress(self, value):
        stage = value.get("stage")
        self.download_title.set({"manifest": "获取运行环境信息", "download": "正在下载运行环境", "retry": "正在重新连接", "verify": "核对文件完整性", "import": "导入 Docker", "build": "从源码构建", "done": "运行环境已安装"}.get(stage, "正在处理"))
        if stage == "download":
            self.download_progress.set(value["bytes"] / value["total"] * 100)
            eta = value.get("eta")
            suffix = f" · 约 {int(eta // 60)} 分 {int(eta % 60)} 秒" if eta else ""
            self.download_detail.set(f"{size_text(value['bytes'])} / {size_text(value['total'])} · {size_text(value['speed'])}/s{suffix}")
        else:
            self.download_progress.set(100 if stage == "done" else -1)
            self.download_detail.set({"manifest": "通过所选下载代理读取环境清单。", "verify": "导入前检查 SHA-256 与文件大小。", "import": "下载已完成，正在导入 Docker。", "build": "构建输出显示在运行日志中。", "done": "运行环境已核验，可以继续。", "retry": "保留已有进度，正在重连。"}.get(stage, "正在处理…"))

    def check_docker(self, auto_start_override=None):
        if self.busy:
            return
        self.startup_active, self.startup_error = True, None
        auto = self.auto_start_docker.get() if auto_start_override is None else auto_start_override
        log.info("docker-check-start auto-start=%s", auto)
        def done(result):
            self.prepared(result)
            log.info("docker-check-ready runtime=%s", self.runtime_ok)
        self.run(lambda engine: prepare_workspace(engine, progress=self.preparation_progress, cancel=self.cancel, auto_start=auto, install=False, check=False), done, True)

    def prepared(self, result):
        self.startup_active = False
        self.docker_ready = True
        self.last_docker_info = result["docker"]
        self.runtime_ok = result["runtime"]
        self.docker_text.set(f"Docker {result['docker']['docker']} · {result['docker']['architecture']}")
        self.runtime_text.set("运行环境已核验" if self.runtime_ok else "点击一键准备，获取运行环境")
        self.steps[0], self.steps[1] = "已就绪", "已核验" if self.runtime_ok else "等待安装"
        self.startup_progress.set(100 if self.runtime_ok else 25)
        self.startup_title.set("运行环境已准备好" if self.runtime_ok else "Docker 已就绪")
        self.startup_detail.set("配置线路与落地，再核对出口。" if self.runtime_ok else "点击一键准备，下载并校验运行环境。")

    def consent_stop(self):
        return status_snapshot(self.store)["phase"] != "ready" or self.ask("更新连接", "此操作会停止当前环境，请先保存项目。继续？")

    def prepare(self, install=True, check=True, source=False):
        if self.busy or not self.consent_stop():
            return
        try:
            values = self.captured_settings()
        except SPXError as error:
            self.notify("检查线路设置", error)
            return
        self.startup_active, self.startup_error = True, None
        self.page_requested.emit("overview")
        def done(result):
            self.prepared(result)
            if result["phase"] == "needs_configuration":
                self.page_requested.emit("connection")
                if not self.nodes:
                    self.proxy_requested.emit()
            elif result["phase"] == "review":
                self.confirm()
            elif result["phase"] == "ready":
                self.page_requested.emit("workspace")
        self.run(lambda engine: prepare_workspace(engine, values, self.preparation_progress, self.cancel, install=install, check=check, source=source), done, True)

    def pause(self):
        self.cancel.set()
        self.operation.set("正在安全取消，已有下载和数据会保留…")
        self.refresh()

    def next_step(self):
        if not self.runtime_ok or not self.docker_ready:
            self.prepare()
        elif not self.nodes:
            self.page_requested.emit("connection")
            self.proxy_requested.emit()
        elif self.view.get("ready"):
            self.page_requested.emit("workspace")
        elif self.view.get("can_confirm"):
            self.confirm()
        else:
            self.prepare()

    def confirm(self):
        if not self.settings_match():
            return
        evidence = status_snapshot(self.store).get("evidence") or {}
        text = f"前置线路出口：{evidence.get('line_ip', '—')}\n落地出口：{evidence.get('ip', '—')}\n地区：{evidence.get('country', '—')} / {evidence.get('city', '—')}\n时区：{self.timezone.get()}\n\n确认实际出口后启用工作区？"
        if self.ask("核对线路与落地", text):
            self.run(lambda engine: engine.confirm())

    def save_settings(self):
        try:
            values = self.captured_settings()
        except SPXError as error:
            self.notify("检查设置", error)
            return
        self.run(lambda engine: engine.save_settings(*values))

    def save_startup_preference(self):
        value = self.auto_start_docker.get()
        def action(engine):
            with engine.store.lock():
                settings = engine.store.settings()
                settings["auto_start_docker"] = value
                engine.store.write("settings.json", settings)
        self.run(action)

    def read_system_proxy(self):
        try:
            self.relay_url.set(detect_system_proxy())
            self.operation.set("已读取本机下载代理；工作区线路模式保持当前选择。")
        except SPXError as error:
            self.notify("填写本机代理", error)

    def save_proxy(self, values):
        try:
            node = normalize({"type": values["type"].lower(), "server": values["server"], "server_port": values["port"], "username": values["username"], "password": values["password"]}, values["name"])
        except (ValueError, TypeError) as error:
            raise SPXError("请检查服务器、端口和认证信息。") from error
        nodes = [node, *[other for other in self.nodes if other["id"] != node["id"]]]
        self.run(lambda engine: engine.save_nodes(nodes), lambda result: self.refresh_nodes())

    def import_nodes(self, text, subscription=False):
        try:
            settings = relay_config(False, self.relay_url.get(), self.relay_downloads.get()) if subscription else None
        except SPXError as error:
            self.notify("检查下载代理", error)
            return False
        def action(engine):
            nodes, warnings = parse_nodes(fetch_subscription(text, download_proxy(settings)[0]) if subscription else text)
            engine.save_nodes(nodes, append=True)
            return len(nodes), warnings
        def done(result):
            self.refresh_nodes()
            self.operation.set(f"已导入 {result[0]} 个节点。")
            if result[1]:
                self.notify("已跳过部分节点", "\n".join(result[1][:10]))
        return self.run(action, done)

    def open_terminal(self, tool):
        if not self.settings_match():
            self.page_requested.emit("connection")
            return
        path = self.project.get().strip()
        if path:
            self.run(lambda engine: engine.terminal(path, tool))
        else:
            self.notify("先选择项目", "请选择要交给工具读写的具体项目文件夹。")

    def terminal_config(self):
        return terminal.validate({"kind": self.terminal_kind.get(), "executable": self.terminal_exe.get(), "arguments": self.terminal_args.get()})

    def detect_terminal(self):
        def done(result):
            self.terminal_kind.set(result[0])
            self.terminal_exe.set(result[1])
            self.terminal_status.set("已找到 " + result[1])
        self.run(lambda engine: terminal.resolve({"kind": "auto"}), done)

    def terminal_action(self, save=False):
        try:
            config = self.terminal_config()
        except SPXError as error:
            self.notify("检查终端设置", error)
            return
        self.run((lambda engine: engine.save_terminal(config)) if save else (lambda engine: terminal.test(config, engine.docker.environment())), lambda result: self.terminal_status.set("终端设置已保存。" if save else "测试终端已打开，请检查窗口是否正确。"))

    def migrate_data(self):
        target = self.data_target.get().strip()
        def reviewed(plan):
            text = f"当前位置：{plan['source']}\n目标位置：{plan['target']}\n数据大小：{size_text(plan['bytes'])}\n可用空间：{size_text(plan['free'])}\n\n会停止工作区，复制校验后切换默认位置并清理已校验的副本。继续？"
            if not self.ask("迁移应用数据", text):
                return
            def move(engine):
                def action():
                    return engine.migrate_storage(target, lambda value: self.events.put(("storage", value)))
                if self.report:
                    with self.report.suspended_for_migration():
                        return action()
                return action()
            def done(result):
                self.store = Store(Path(result["target"]))
                if self.on_relocated and self.on_relocated(self.store) is False:
                    self.close_requested.emit()
                    return
                self.data_location.set(str(self.store.home))
                self.data_target.set(str(self.store.home))
                self.storage_progress.set(100)
                self.storage_status.set("已迁移至 " + str(self.store.home) + "，请重新检查连接。")
                self.refresh_nodes()
                if result["leftovers"]:
                    self.notify("数据已迁移", "新位置已生效。原位置有少量文件未清理，详情见 storage-migration.json。")
                self.check_docker()
            self.run(move, done)
        self.run(lambda engine: plan_migration(engine.store, target), reviewed)

    def detect_storage(self):
        def done(result):
            total = sum(item["bytes"] for item in result["disks"])
            self.docker_location.set(f"{result['folder']}\n找到 {len(result['disks'])} 个数据盘，文件长度合计 {size_text(total)}。稀疏文件的实际占用可能更小。")
        self.run(lambda engine: desktop_storage(), done)

    def prepare_docker_move(self):
        target = self.docker_target.get().strip()
        if not self.ask("准备 Docker 数据盘迁移", f"目标位置：{target or '尚未选择'}\n\n会停止本工作区并记录镜像、容器和账号卷。随后需在 Docker Desktop 中选择同一路径确认迁移。请先保存其他 Docker 软件中的工作。继续？"):
            return
        self.run(lambda engine: prepare_docker_move(engine, target), lambda result: self.docker_move_status.set("迁移计划已保存。请在 Docker Desktop 的 Disk image location 选择 " + result["target"] + "，完成后回来核验。"))

    def verify_docker_move(self):
        def done(result):
            self.docker_location.set(result["detected"])
            self.docker_move_status.set("已找到原镜像、容器和数据卷，请重新检查连接。")
            self.check_docker()
        self.run(verify_docker_move, done)

    def export_v2ray(self, path):
        node = next((node for node in self.nodes if node["id"] == self.selected.get()), None)
        if node is None:
            self.notify("先选择落地", "请先导入并选择一个落地节点。")
            return
        try:
            atomic_json(Path(path), v2ray_rules(node))
            self.notify("路由规则已导出", "在 v2rayN 中导入并置顶，确认 proxy 出口使用指定线路且没有直连回退。外部客户端仍负责前置路径。")
        except OSError as error:
            self.notify("无法保存", error, True)

    def help(self):
        if self.startup_error == "docker_missing":
            webbrowser.open(DOCKER_INSTALL_URL)
        elif self.startup_error in ("docker_timeout", "docker_configuration", "launch_failed"):
            self.check_docker(True)
        else:
            webbrowser.open(PROJECT_URL + "/blob/main/docs/quickstart.zh-CN.md")

    def diagnostics(self):
        result = diagnostics(self.store, self.last_docker_info, self.startup_error)
        result.update(theme="warm-clay", window_frame="qt-native")
        return json.dumps(result, ensure_ascii=False, indent=2)

    def request_close(self):
        log.info("gui-close-requested busy=%s", self.busy)
        if not self.busy:
            return True
        if self.cancelable and self.ask("取消并退出", "取消当前准备并退出？已下载内容会保留，Docker Desktop 继续运行。"):
            self.close_pending = True
            self.pause()
        elif not self.cancelable:
            self.notify("操作进行中", "请等待当前操作安全完成后再退出。")
        return False

    def refresh(self):
        try:
            state = status_snapshot(self.store)
            matching = self.settings_match()
            ready = state["phase"] == "ready" and matching and self.compatible and self.docker_ready and state["guard_age"] <= 100
            title = "连接已确认，可以开始工作" if ready else "核对出口后开始工作" if state["phase"] == "review" else "准备你的工作环境"
            detail = state.get("reason") or "为 Claude Code、Codex 和浏览器准备独立工作区。"
            if not self.runtime_ok:
                title, detail = "准备你的工作环境", "一键准备运行环境，然后配置线路与落地代理。"
            elif not self.nodes:
                title, detail = "添加你的落地代理", "选择合适的出口，连接你的工作环境。"
            elif state["phase"] in ("ready", "review") and not matching:
                title, detail = "代理设置已更改", "重新检查线路，并核对实际出口后启用。"
            elif state["phase"] == "ready" and not ready:
                title, detail = "连接需要重新核验", "检查当前环境，再核对线路和落地出口。"
            if self.startup_active:
                title, detail = self.startup_title.get(), self.startup_detail.get()
            elif self.startup_error:
                title, detail = "完成 Docker 准备后继续", self.startup_detail.get()
            evidence = state.get("evidence") or {}
            if ready:
                self.steps[2:] = ["检查通过", "已确认"]
            elif state["phase"] == "review":
                self.steps[3] = "等待你确认"
            elif not self.busy:
                self.steps[2:] = ["等待检查", "由你确认"]
            mode = self.line_mode.get()
            line_status = "软件内双跳：固定加密线路，不配置直连备用出口。" if self.relay_enabled.get() and mode == "managed" else "v2ray 兼容：前置分流由外部客户端负责，请正确配置。" if self.relay_enabled.get() else "未启用前置线路：本机会连接所选落地代理。"
            node = next((node for node in self.nodes if node["id"] == self.selected.get()), None)
            route = "选择线路与落地，指定工作区的网络路径。"
            if node:
                value = node["outbound"]
                prefix = ("加密线路  →  " if mode == "managed" else "本机 v2ray  →  ") if self.relay_enabled.get() else ""
                route = prefix + f"{protocol(node)} 落地  {value['server']}:{value['server_port']}  →  目标服务"
            next_text = "一键准备环境" if not self.runtime_ok or not self.docker_ready else "添加落地代理" if not self.nodes else "打开工作区" if ready else "核对并确认" if state["phase"] == "review" and matching else "启动并检查连接"
            view = dict(title=title, detail=detail, ready=ready, matching=matching, busy=self.busy, cancelable=self.cancelable and not self.cancel.is_set(), next_text=next_text, steps=tuple(self.steps), route=route, line_status=line_status,
                        ip=evidence.get("ip", "—"), line_ip=evidence.get("line_ip", "—"), region=evidence.get("country", "—") + " / " + evidence.get("city", "—"), timezone=self.timezone.get(),
                        badge="工作区已就绪" if ready else "正在准备" if self.busy else "等待确认" if state["phase"] == "review" else "尚未启用",
                        can_confirm=not self.busy and self.docker_ready and state["phase"] == "review" and matching)
            if view != self.view:
                self.view = view
                self.changed.emit(view)
        except Exception as error:
            if self.report:
                self.report.capture("gui-refresh-error", type(error), error, error.__traceback__)
            self.operation.set("状态暂不可用，请查看诊断日志。")
