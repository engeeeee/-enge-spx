"""Desktop state and bounded worker delivery, independent of widget layouts."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import webbrowser

from PySide6.QtCore import QObject, QTimer, Signal

from .. import terminal
from ..brand import PROJECT_URL
from ..downloads import DownloadPaused
from ..desktop_shutdown import load_preference as load_exit_preference, save_preference as save_exit_preference, stop_desktop
from ..engine import Engine
from ..gui_diagnostics import log
from ..exit_diagnostics import capture_checks, failure_report
from .. import __version__
from ..line_security import LINE_MODES, v2ray_rules
from ..nodes import fetch_subscription, normalize, parse_nodes
from ..proxy import detect_system_proxy, download_proxy, protocol, proxy_url, relay_config, route_config
from ..resource_limits import ROLES, preset as resource_preset, validate as validate_resources, validate_budget
from ..workspace_profiles import load as load_workspace_profiles, display_name as workspace_display_name, SHARED
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
    exit_failed = Signal(str)
    workspace_changed = Signal()

    def __init__(self, store, report=None, on_relocated=None):
        super().__init__()
        self.store, self.report, self.on_relocated = store, report, on_relocated
        self.ask = lambda title, text: False
        self.busy = self.cancelable = self.close_pending = False
        self.exit_mode = None
        self.exit_stage = "idle"
        self.exit_workspace_stopped = False
        self.exit_desktop_done = False
        self.exit_docker = None
        self.exit_close_desktop = False
        self.exit_skip_desktop = False
        self.exit_diagnostics = None
        self.desktop_exit_supported = os.name == "nt"
        try:
            self.saved_close_desktop = load_exit_preference(store)
            exit_message = "退出偏好已保存。" if self.saved_close_desktop else "默认保留 Docker Desktop；勾选并保存后，真正退出时一起关闭。"
        except SPXError as error:
            self.saved_close_desktop = False
            exit_message = str(error)
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
        try:
            self.workspace_config = load_workspace_profiles(store)
            workspace_message = "默认共享模式沿用旧账号与浏览器资料。新身份使用独立资料，需要重新登录。"
        except SPXError as error:
            self.workspace_config = None
            workspace_message = str(error)
        self.network_report = None
        self.network_performance_report = None
        try:
            self.resource_config = validate_resources(settings.get("resources"))
            resource_message = "预算保存后在下次启动应用；不会重建项目容器。"
        except SPXError:
            self.resource_config = resource_preset()
            resource_message = "保存的资源设置无效，请选择正常模式并保存以恢复。"
        self._loading_resources = False
        self.resource_visible = self.resource_inflight = self.ui_background = False
        self.resource_closed = False
        self.resource_epoch = 0
        self.resource_monitor = None
        self.resource_cancel = threading.Event()
        self.record_pending = self.record_after = None
        self.record_running = False
        self.record_cancel = threading.Event()
        self.record_reason = "user_stop"
        self.record_id = 0
        self.last_record_report = None
        self.resource_projects = dict(self.resource_config["projects"])
        relay, term = settings["relay"], terminal.validate(settings["terminal"])
        defaults = {
            "selected": settings["selected"], "line_selected": relay.get("line_id", ""),
            "timezone": settings["timezone"], "context": settings["context"],
            "project": (settings["projects"] or [""])[-1], "relay_enabled": relay.get("enabled", False),
            "relay_url": proxy_url(relay) or "", "relay_downloads": relay.get("downloads", True),
            "line_mode": relay.get("mode", "local" if relay.get("enabled") else "managed"),
            "line_server_ip": relay.get("server_ip", ""), "line_expected_ip": relay.get("expected_ip", ""),
            "terminal_kind": term["kind"], "terminal_exe": term["executable"], "terminal_args": term["arguments"],
            "terminal_status": "工作区、Linux 终端和登录窗口使用相同的终端设置。",
            "data_location": str(store.home), "data_target": "D:\\ENGE-SPX\\data" if os.name == "nt" and Path("D:/").exists() else "",
            "docker_target": store.read("docker-move.json", {}).get("target", "D:\\DockerData" if os.name == "nt" and Path("D:/").exists() else ""),
            "docker_location": "检测后显示 Docker 数据盘位置。", "storage_status": "配置、日志和下载缓存可迁移到自选目录。",
            "docker_move_status": "Docker Desktop 负责实际迁移，完成后回到这里核验。",
            "operation": "就绪", "startup_title": "准备你的工作环境", "startup_detail": "点击一键准备，启动 Docker 与运行环境，再核对代理出口。",
            "docker_text": "尚未检测 Docker", "runtime_text": "等待核验已有环境" if self.runtime_ok else "尚未安装运行环境",
            "download_title": "获取运行环境", "download_detail": "支持暂停与断点续传，导入前校验完整性。",
            "download_progress": 0, "startup_progress": 0, "storage_progress": 0,
            "resource_mode": self.resource_config["mode"], "auto_browser": self.resource_config["auto_browser"],
            "resource_status": resource_message, "resource_caption": "仅此页可见时采样；不会自动启动 Docker。",
            "resource_app_text": "等待采样。", "resource_system_text": "等待采样。", "resource_container_text": "等待采样。",
            "record_seconds": 900, "record_activity": "unspecified", "record_active": False, "record_available": False,
            "record_status": "主动记录真实使用过程；记录期间可继续操作工作区，最小化和托盘中也会继续。停止或退出时保存。",
            "close_docker_desktop": self.saved_close_desktop, "exit_preferences_status": exit_message,
            "project_budget_enabled": False, "project_budget_cpu": 0, "project_budget_memory": 4096,
            "workspace_profile": self.workspace_config["selected"] if self.workspace_config else "",
            "workspace_access": "rw", "workspace_status": workspace_message,
            "network_summary": "由你主动检查当前已应用的工作区。不自动启动 Docker 或浏览器，不更改语言或时区。",
            "network_evidence": "尚未检查。结果会标明宿主、容器、浏览器、第一跳和最终出口；导出时地址使用每份报告独立的代号。",
            "network_performance_available": False,
            "network_performance_summary": "尚未测量。通过最终出口访问 Cloudflare，最多 3 次测速请求、约 1 MiB 载荷；前后出口复核流量另计，不上传报告。",
            "network_performance_evidence": "HTTPS 首字节耗时包含代理 CONNECT、TLS 与服务响应，不是 RTT。现有第一跳/最终出口复核耗时单独记录。",
        }
        for role in ROLES:
            defaults["budget_" + role + "_cpu"] = self.resource_config["budgets"][role]["cpus"]
            defaults["budget_" + role + "_memory"] = self.resource_config["budgets"][role]["memory_mb"]
        self.values = {name: Value(value, self) for name, value in defaults.items()}
        for name, value in self.values.items():
            setattr(self, name, value)
        self.steps = ["等待检测", "等待核验", "等待配置", "由你确认"]
        for name in ("selected", "line_selected", "timezone", "context", "relay_enabled", "relay_url", "relay_downloads", "line_mode", "line_server_ip", "line_expected_ip"):
            self.values[name].changed.connect(lambda unused: self.schedule_refresh())
        self.resource_mode.changed.connect(self.resource_preset_changed)
        self.close_docker_desktop.changed.connect(lambda value: self.exit_preferences_status.set("更改尚未保存；点击“保存退出偏好”后生效。" if value != self.saved_close_desktop else "退出偏好已保存。"))
        for name, value in self.values.items():
            if name.startswith("budget_") or name == "auto_browser":
                value.changed.connect(self.mark_resource_custom)
        self.project.changed.connect(lambda unused: self.load_project_budget())
        self.load_project_budget()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(40)
        self.refresh_timer.timeout.connect(self.refresh)
        self.delivery = QTimer(self)
        self.delivery.setInterval(40)
        self.delivery.timeout.connect(self.drain)
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(5000 if self.resource_config["mode"] == "low" else 3000)
        self.status_timer.timeout.connect(self.refresh)
        self.status_timer.start()
        self.resource_timer = QTimer(self)
        self.resource_timer.setInterval(15000 if self.resource_config["mode"] == "low" else 10000)
        self.resource_timer.timeout.connect(self.sample_resources)
        self.project.changed.connect(lambda unused: self.load_workspace_project())
        self.workspace_profile.changed.connect(lambda unused: self.workspace_selection_changed())
        self.workspace_access.changed.connect(lambda unused: self.workspace_selection_changed())
        self.load_workspace_project()
        self.refresh_nodes()

    def load_workspace_project(self):
        if not self.workspace_config:
            return
        binding = self.workspace_config["projects"].get(self.project_budget_key())
        self.workspace_profile.set(binding["profile"] if binding else self.workspace_config["selected"])
        self.workspace_access.set(binding["access"] if binding else "rw" if self.workspace_profile.get() == SHARED else "ro")
        self.workspace_selection_changed()

    def workspace_selection_matches(self, require_project=True):
        config = self.workspace_config
        if not config or self.workspace_profile.get() != config["selected"]:
            return False
        if not require_project:
            return True
        key = self.project_budget_key()
        binding = config["projects"].get(key)
        return bool(key) and ((binding is None and config["selected"] == SHARED and self.workspace_access.get() == "rw") or binding == {"profile": self.workspace_profile.get(), "access": self.workspace_access.get()})

    def workspace_selection_changed(self):
        config = self.workspace_config
        if not config:
            return
        current = config["profiles"].get(config["selected"], "未知身份")
        selected = config["profiles"].get(self.workspace_profile.get(), "未选择")
        access = "只读" if self.workspace_access.get() == "ro" else "读写"
        if self.workspace_selection_matches():
            self.workspace_status.set(f"当前身份：{current} · 项目{access}。浏览器、Claude Code 和 Codex 资料仅在同一身份内共享。")
        else:
            self.workspace_status.set(f"当前运行身份：{current}。待应用：{selected} · 项目{access}；应用前不会启动所选身份的工具。")

    def reload_workspaces(self, config):
        self.workspace_config = config
        self.load_workspace_project()
        self.workspace_changed.emit()
        self.refresh()

    def create_workspace(self, name):
        try:
            name = workspace_display_name(name)
        except SPXError as error:
            self.notify("检查身份名称", error)
            return False
        def done(result):
            self.reload_workspaces(result["config"])
            self.workspace_profile.set(result["profile"])
            self.workspace_access.set("ro")
            self.operation.set("空白身份已创建。选择项目和目录权限后点击“应用身份与授权”。")
        return self.run(lambda engine: engine.create_workspace_profile(name), done, description="创建空白身份，保留已有账号资料…")

    def apply_workspace(self, restore=False):
        if self.busy or self.exit_mode is not None:
            return False
        identity, access, path = self.workspace_profile.get(), self.workspace_access.get(), self.project.get().strip()
        if not restore and self.workspace_selection_matches(require_project=bool(path)):
            self.operation.set("当前身份与项目目录权限已应用。")
            return False
        if status_snapshot(self.store)["phase"] in ("review", "ready") and not self.ask("应用工作区身份", "这会停止当前工作区。请保存工具和浏览器中的工作，再重新检查并确认连接。新身份从空白账号资料开始，原资料保留。继续？"):
            return False
        def action(engine):
            config = engine.restore_workspace_profiles() if restore else engine.configure_workspace(identity, path or None, access)
            canonical = str(engine.store.project(path)[0]) if path and not restore else None
            return config, canonical
        def done(result):
            self.workspace_config = result[0]
            if result[1]:
                self.project.set(result[1])
            self.reload_workspaces(result[0])
            self.operation.set("身份与目录权限已应用。重新检查并确认连接后开始工作。")
        return self.run(action, done, description="停止当前工作区并应用身份与目录授权…")

    def open_workspace_browser(self):
        if not self.workspace_selection_matches(require_project=False):
            self.page_requested.emit("workspace")
            self.notify("先应用身份", "请先应用所选身份并重新确认连接，再打开该身份的浏览器。")
            return False
        identity = self.workspace_profile.get()
        return self.run(lambda engine: engine.browser(expected_profile=identity))

    def check_network(self):
        def done(report):
            self.network_report = report
            self.network_evidence.set(json.dumps(report, ensure_ascii=False, indent=2))
            state = report.get("status")
            summary = {"checked": "已完成本次检查。连接保持确认；请结合证据范围阅读结果，超时不等于证明没有发包。", "partial": "已完成部分检查；浏览器未运行、探测超时或部分信息不可用。未执行项不计为通过。", "not_ready": "工作区尚未确认，未启动任何环境。请先检查并确认连接后重试。", "unsafe": "发现工作区存在成功直连或权限异常，已请求停止。", "failed": "已确认连接的复核失败，已请求停止；请查看失败阶段并重新检查连接。"}.get(state, "诊断结果不可用。")
            if state in ("unsafe", "failed"):
                summary += "已核验停止。" if report.get("stop", {}).get("verified") else "未能确认停止，请检查 Docker 状态并重试停止工作区。"
                self.notify("网络检查未通过", summary, True)
            zone = report.get("objects", {}).get("session", {}).get("timezone", {})
            if zone.get("localtime_matches_process_offset") is False or zone.get("localtime_matches_tzif") is False:
                summary += " 检测到进程 TZ 与 /etc/localtime 不一致，详细报告分别列出了来源和偏移；检查未更改时区。"
            self.network_summary.set(summary)
            self.operation.set("网络检查完成，报告已脱敏。")
        return self.run(lambda engine: engine.network_diagnostics(), done, description="检查当前工作区的出口、路由与浏览器环境，不修改宿主网络…")

    def export_network_report(self, path):
        if self.network_report is None:
            self.notify("先运行检查", "请先生成一份当前工作区的网络检查报告。")
            return False
        report = self.network_report
        return self.run(lambda engine: atomic_json(Path(path), report), lambda result: self.operation.set("脱敏报告已导出，不含项目路径、账号、代理凭据或原始 SDP。"), description="导出脱敏网络报告…")

    def check_network_performance(self):
        if self.busy or self.exit_mode is not None:
            return False
        self.network_performance_report = None
        self.network_performance_available.set(False)
        self.network_performance_summary.set("本次测量尚未产生可导出结果，请查看操作状态。")
        self.network_performance_evidence.set("等待本次结果；不会使用上次测速冒充本次数据。")
        def done(report):
            self.network_performance_report = report
            self.network_performance_available.set(True)
            self.network_performance_evidence.set(json.dumps(report, ensure_ascii=False, indent=2))
            status = report.get("status")
            summary = {"checked": "测量完成，前后出口与拓扑已复核。", "partial": "目标测速未完整完成；出口已重新复核，失败样本不计为零速度。", "stale": "测量期间工作区已变化，结果已丢弃，未停止替换后的工作区。", "not_ready": "请先检查并确认工作区；没有启动 Docker、浏览器或进行测速。", "failed": "TLS、出口或拓扑检查失败，已请求停止本实例；请检查停止证据。"}.get(status, "测速结果不可用。")
            result = report.get("measurement", {})
            latency = result.get("cold_https_first_byte_ms", {}).get("median")
            rate = result.get("download", {}).get("request_mbps")
            if type(latency) in (int, float):
                summary += f" HTTPS 首字节中位数 {latency:.1f} ms。"
            if type(rate) in (int, float):
                summary += f" 单次请求有效下载 {rate:.2f} Mbps。"
            self.network_performance_summary.set(summary)
            self.operation.set("网络测量结束，结果与范围已记录。")
        return self.run(lambda engine: engine.network_performance(), done, description="复核连接并进行有界 HTTPS 测量；真正退出会等待收尾…")

    def export_network_performance(self, path):
        if self.network_performance_report is None:
            self.notify("先运行测速", "请先生成本次网络测量报告。")
            return False
        report = self.network_performance_report
        return self.run(lambda engine: atomic_json(Path(path), report), lambda result: self.operation.set("脱敏测速报告已保存，没有重新测量或上传。"), description="保存脱敏测速报告…")

    def mark_resource_custom(self, unused):
        if not self._loading_resources:
            self.resource_mode.set("custom")

    def resource_preset_changed(self, mode):
        if self._loading_resources or mode == "custom":
            return
        config = resource_preset(mode)
        self._loading_resources = True
        try:
            for role, limit in config["budgets"].items():
                self.values["budget_" + role + "_cpu"].set(limit["cpus"])
                self.values["budget_" + role + "_memory"].set(limit["memory_mb"])
            self.auto_browser.set(config["auto_browser"])
        finally:
            self._loading_resources = False

    def load_project_budget(self):
        value = self.resource_projects.get(self.project_budget_key())
        self.project_budget_enabled.set(value is not None)
        self.project_budget_cpu.set(value["cpus"] if value else self.resource_config["budgets"]["project"]["cpus"])
        self.project_budget_memory.set(value["memory_mb"] if value else self.resource_config["budgets"]["project"]["memory_mb"])

    def project_budget_key(self):
        path = self.project.get().strip()
        # No network-share stat/resolve on each GUI keystroke. A newly enabled
        # override is resolved and validated by the operation worker at save.
        return hashlib.sha256(os.path.normcase(os.path.abspath(os.path.expanduser(path))).encode()).hexdigest()[:16] if path else None

    def captured_resources(self):
        projects = dict(self.resource_projects)
        if not self.project.get().strip() and self.project_budget_enabled.get():
            raise SPXError("请先在项目工作区选择项目，再设置独立预算。")
        if not self.project_budget_enabled.get():
            projects.pop(self.project_budget_key(), None)
        return validate_resources({"schema": 1, "mode": self.resource_mode.get(), "budgets": {role: {"cpus": self.values["budget_" + role + "_cpu"].get(), "memory_mb": self.values["budget_" + role + "_memory"].get()} for role in ROLES}, "projects": projects, "auto_browser": self.auto_browser.get()})

    def resource_saved(self, config):
        self.resource_config = config
        self.resource_projects = dict(config["projects"])
        self._loading_resources = True
        try:
            self.resource_mode.set(config["mode"])
            self.auto_browser.set(config["auto_browser"])
            for role, value in config["budgets"].items():
                self.values["budget_" + role + "_cpu"].set(value["cpus"])
                self.values["budget_" + role + "_memory"].set(value["memory_mb"])
        finally:
            self._loading_resources = False
        self.load_project_budget()
        self.set_background(self.ui_background)
        self.resource_timer.setInterval(15000 if config["mode"] == "low" else 10000)
        self.resource_status.set("资源设置已保存。重新检查连接后应用；项目、账号和浏览器资料保留。")

    def save_resources(self, restore=False):
        try:
            config = self.captured_resources() if not restore else None
            project = self.project.get().strip()
            override = validate_budget({"cpus": self.project_budget_cpu.get(), "memory_mb": self.project_budget_memory.get()}, "project") if self.project_budget_enabled.get() and not restore else None
        except (SPXError, OSError) as error:
            self.notify("检查资源设置", error)
            return
        if status_snapshot(self.store)["phase"] in ("ready", "review") and not self.ask("应用资源预算", "变更资源预算会停止本工作区。请先保存终端和浏览器中的工作，再重新检查连接。较低的内存上限可能使工具内存不足。继续？"):
            return
        def action(engine):
            canonical = None
            if restore:
                return engine.restore_resources(), canonical
            if override is not None:
                directory, key = engine.store.project(project)
                config["projects"][key] = override
                canonical = str(directory)
            return engine.save_resources(config), canonical
        def done(result):
            if result[1]:
                self.project.set(result[1])
            self.resource_saved(result[0])
        self.run(action, done, description="保存资源预算，保留原有容器与数据…")

    def set_background(self, background):
        self.ui_background = background
        self.status_timer.setInterval(10000 if background else 5000 if self.resource_config["mode"] == "low" else 3000)

    def set_resource_visible(self, visible):
        visible = visible and self.exit_mode is None
        if self.resource_closed or self.resource_visible == visible:
            return
        self.resource_visible = visible
        self.resource_epoch += 1
        if visible:
            self.resource_timer.start()
            self.sample_resources()
        else:
            self.resource_timer.stop()
            self.resource_cancel.set()

    def sample_resources(self):
        if self.resource_closed or not self.resource_visible or self.resource_inflight or self.busy:
            return
        self.resource_inflight = True
        self.resource_cancel.clear()
        epoch, store, ready = self.resource_epoch, self.store, self.docker_ready
        context = (self.last_docker_info or {}).get("context")
        def worker():
            try:
                from ..resource_monitor import Monitor, sampling_target
                if self.resource_monitor is None:
                    self.resource_monitor = Monitor()
                target = sampling_target(store, context)
                value = self.resource_monitor.snapshot(target, ready and target.ready, self.resource_cancel)
            except Exception:
                value = None
            self.events.put(("resources", (epoch, value)))
        self.delivery.start()
        threading.Thread(target=worker, name="spx-resource-sample", daemon=True).start()

    def start_resource_recording(self, path):
        from ..resource_recording import settings
        if self.resource_closed or self.exit_mode is not None or self.record_active.get() or self.record_after:
            return False
        try:
            config = settings(self.record_seconds.get(), 10, self.record_activity.get())
        except SPXError as error:
            self.notify("检查记录设置", error, True)
            return False
        self.record_id += 1
        self.record_pending = (Path(path), config, self.record_id)
        self.record_active.set(True)
        self.resource_timer.stop()
        self.record_status.set("等待当前操作或采样结束后开始记录…" if self.resource_inflight or self.busy else "正在开始记录…")
        self.delivery.start()
        self._start_pending_recording()
        return True

    def _start_pending_recording(self):
        if self.record_pending is None or self.resource_inflight or self.busy or self.resource_closed or self.exit_mode is not None:
            return
        path, config, identifier = self.record_pending
        self.record_pending = None
        self.resource_inflight = self.record_running = True
        self.last_record_report = None
        self.record_available.set(False)
        self.record_cancel.clear()
        self.record_reason = "user_stop"
        store = self.store
        def worker():
            report, failed, recorder = None, False, None
            try:
                from ..resource_monitor import Monitor, sampling_target
                from .. import resource_recording as recorder
                monitor = Monitor()
                def sample(cancel):
                    target = sampling_target(store, (self.last_docker_info or {}).get("context"))
                    return monitor.snapshot(target, self.docker_ready and target.ready and not self.busy, cancel)
                report = recorder.record(sample, output=path,
                                **config, source="gui", cancel=self.record_cancel, stop_reason=lambda: self.record_reason,
                                on_sample=lambda raw, count, elapsed: self.events.put(("record_sample", (identifier, raw, count, elapsed))))
            except Exception as error:
                failed = True
                if recorder is not None and isinstance(error, recorder.RecordingError):
                    report = error.report
                elif self.report:
                    self.report.capture("resource-recording-error", type(error), error, error.__traceback__)
            self.events.put(("record_done", (identifier, report, failed)))
        self.record_status.set("正在记录；可使用 Claude/Codex 或浏览器。停止或真正退出时保存结果。")
        self.delivery.start()
        threading.Thread(target=worker, name="spx-resource-record", daemon=True).start()

    def stop_resource_recording(self, reason="user_stop"):
        if not self.record_active.get():
            return
        self.record_reason = reason
        if self.record_pending is not None:
            self.record_pending = None
            self.record_active.set(False)
            self.record_status.set("已取消等待，尚未开始记录。")
            if self.resource_visible and not self.resource_closed and self.exit_mode is None:
                self.resource_timer.start()
        else:
            self.record_cancel.set()
            self.record_status.set("正在结束采样并保存已收集的脱敏记录…")
        self.delivery.start()

    def resource_recording_done(self, identifier, report, failed):
        if identifier != self.record_id:
            return
        self.record_running = self.resource_inflight = False
        self.record_active.set(False)
        self.resource_monitor = None
        failed = failed or not isinstance(report, dict)
        if report is not None:
            self.last_record_report = report
            self.record_available.set(True)
        if failed:
            self.record_status.set("报告未能保存；可重新导出已采集的结果。选定文件旁的 .partial 中间记录会保留。" if report is not None else "本次未能生成报告。已写入的 .partial 中间文件可保留排障；安全监测不受影响。")
            if self.exit_mode is None:
                self.notify("性能记录保存未完成", self.record_status.get(), True)
        else:
            self.record_status.set(f"已保存 {report['sample_count']} 份采样，实际记录 {report['elapsed_seconds']:.1f} 秒。活动标签由用户选择，未读取 AI 输入或账号。")
        if self.resource_visible and not self.resource_closed and self.exit_mode is None:
            self.resource_timer.start()
        if self.exit_mode is not None and self.exit_stage == "finalizing":
            self.finish_exit_when_quiet()

    def export_resource_recording(self, path):
        if self.last_record_report is None or self.record_active.get():
            self.notify("先结束记录", "停止记录后可以重新导出最近一次结果。")
            return False
        report = self.last_record_report
        return self.run(lambda engine: atomic_json(Path(path), report), lambda result: self.operation.set("脱敏性能记录已导出。"), description="导出已采集的性能记录…")

    def resources_received(self, evidence):
        if evidence is None:
            self.resource_caption.set("资源采样暂不可用；安全监测继续独立运行。")
            return
        def cpu(value):
            return "采样中" if value is None else f"{value:.2f}%"
        def process_line(row):
            return row["name"] + (f" · CPU {cpu(row.get('cpu_percent'))} · 工作集 {size_text(row['memory_bytes'])}" if row.get("available") else " · 无法读取，进程可能已退出或权限不足")
        self.resource_app_text.set("\n".join(process_line(row) for row in evidence["app"]) + ("\n部分后台进程未能读取或已退出。" if evidence["background_unavailable"] else ""))
        host = evidence["host"]
        lines = [f"主机整体 · CPU {cpu(host.get('cpu_percent'))} · 内存 {size_text(host['memory_used'])} / {size_text(host['memory_total'])}" if host.get("available") else "主机整体计数不可用。"]
        lines += [process_line(row) for row in evidence["desktop"]]
        if not evidence["desktop"]:
            lines.append("未检测到可读的 Docker Desktop / WSL2 进程。" if evidence["windows"] else "当前为 Linux；不显示 Windows Desktop / WSL2 进程计数。")
        self.resource_system_text.set("\n".join(lines))
        data = evidence["containers"]
        lines = []
        for row in data["rows"]:
            title = ROLES[row["role"]] + (" · " + row["name"].rsplit("-", 1)[-1][:8] if row["role"] == "project" else "")
            if not row["running"]:
                lines.append(title + (" · 已停止（内存不足 OOM）" if row["oom"] else " · 已停止"))
                continue
            configured = row["memory_limit"]
            reported = row.get("reported_memory_limit", 0)
            limit = size_text(reported) if reported else size_text(configured) if configured else "共享 Docker/WSL2 上限"
            if configured and reported and reported != configured:
                limit += f"（配置 {size_text(configured)}）"
            if row["sample_available"]:
                lines.append(f"{title} · CPU {cpu(row['cpu_percent'])} · 内存 {size_text(row['memory_bytes'])} / {limit}\n累计磁盘读 {size_text(row['read_bytes'])} / 写 {size_text(row['write_bytes'])} · CPU 上限 {str(row['cpu_limit']) + ' 核' if row['cpu_limit'] else '不限'}")
            else:
                lines.append(title + " · 运行中，本次计数不可用")
        self.resource_container_text.set("\n\n".join(lines) if lines else "本实例没有容器。" if data["available"] else data["reason"])
        sampled = datetime.fromtimestamp(evidence["sampled"]).strftime("%H:%M:%S")
        self.resource_caption.set(f"采样 {sampled} · 仅资源页可见时每 {self.resource_timer.interval() // 1000} 秒刷新；进程/容器 CPU 以单核 100% 计。" + (" 容器过多，仅展示前 256 个。" if data.get("truncated") else ""))
        if self.record_active.get():
            self.resource_caption.set(f"采样 {sampled} · 正在手动记录；查询之间至少间隔 10 秒，最小化/托盘中继续。CPU 以单核 100% 计。")

    def stop_resource_monitor(self):
        self.resource_closed = True
        self.resource_visible = False
        self.resource_epoch += 1
        self.resource_timer.stop()
        self.resource_cancel.set()
        self.stop_resource_recording("app_exit")

    def schedule_refresh(self):
        self.refresh_timer.start()

    def clean_message(self, text):
        from ..redaction import redact, values
        known = values(self.relay_url.get()) if hasattr(self, "relay_url") else set()
        known.update(values(getattr(self, "nodes", [])))
        return redact(text, known)

    def notify(self, title, text, error=False):
        self.notice.emit(title, self.clean_message(text), error)

    def delete_selected_node(self):
        identifier = self.selected.get()
        if identifier and self.ask("删除代理", "停止当前环境并删除所选代理及派生配置？项目和工具账号会保留。"):
            self.run(lambda engine: engine.delete_node(identifier), lambda result: self.refresh_nodes())

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

    def run(self, action, done=None, cancelable=False, description="正在处理…", done_on_exit=False):
        if self.busy or self.exit_mode is not None:
            return False
        # Any further Engine operation invalidates an earlier shutdown proof.
        self.exit_workspace_stopped = False
        self.exit_docker = None
        self.busy, self.cancelable = True, cancelable
        self.cancel.clear()
        self.operation.set(description)
        self.refresh()

        def worker():
            try:
                engine = Engine(self.store, lambda text: self.events.put(("log", self.clean_message(text))))
                result = action(engine)
                state = self.store.read("runtime.json", {})
                compatible = state.get("phase") != "ready" or state.get("policy") == engine.policy()
                self.events.put(("done", (result, done, compatible, done_on_exit)))
            except DownloadPaused as error:
                self.events.put(("paused", self.clean_message(error)))
            except StartupIssue as error:
                self.events.put(("startup_error", (error.code, self.clean_message(error))))
            except Exception as error:
                if self.report:
                    self.report.capture("gui-worker-error", type(error), error, error.__traceback__)
                self.events.put(("error", self.clean_message(error)))

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
            elif kind == "resources":
                self.resource_inflight = False
                epoch, evidence = value
                if epoch == self.resource_epoch and self.resource_visible and not self.resource_closed:
                    self.resources_received(evidence)
                self._start_pending_recording()
                if self.exit_mode is not None and self.exit_stage == "finalizing":
                    self.finish_exit_when_quiet()
            elif kind == "record_sample":
                identifier, evidence, count, elapsed = value
                if identifier == self.record_id and self.record_running and not self.resource_closed and not self.record_cancel.is_set():
                    if self.resource_visible:
                        self.resources_received(evidence)
                    self.record_status.set(f"正在记录 · {count} 份采样 · {elapsed:.0f} 秒；停止或退出时保存。")
            elif kind == "record_done":
                self.resource_recording_done(*value)
            elif kind == "exit_progress":
                self.operation.set(value)
                self.startup_detail.set(value)
            elif kind == "exit_done":
                self.busy = self.cancelable = False
                result, self.exit_docker = value
                self.exit_workspace_stopped = True
                self.exit_desktop_done = result.get("docker_desktop_stopped") is True
                self.exit_stage = "finalizing"
                log.info("gui-exit-workspace-stopped background=stopped desktop-close-requested=%s", self.exit_close_desktop)
                self.finish_exit_when_quiet()
            elif kind == "desktop_exit_done":
                self.busy = self.cancelable = False
                self.exit_desktop_done = True
                self.exit_stage = "finalizing"
                log.info("gui-exit-desktop-stopped")
                self.finish_exit_when_quiet()
            elif kind == "desktop_exit_error":
                value = self.receive_exit_failure(value)
                self.busy = self.cancelable = self.close_pending = False
                self.exit_mode = None
                self.exit_stage = "failed"
                self.operation.set("工作区已停止；可重试确认 Docker Desktop，或仅本次退出 ENGE SPX。")
                self.exit_failed.emit(value)
            elif kind == "exit_preferences_error":
                self.busy = self.cancelable = False
                self.close_docker_desktop.set(self.saved_close_desktop)
                self.exit_preferences_status.set("退出偏好未保存；请检查数据目录权限和偏好文件，仍使用原设置。")
                if self.exit_mode is not None and self.exit_stage == "waiting":
                    # Never close Desktop under an old choice after saving a
                    # newly selected keep/close preference failed.
                    self.exit_mode = None
                    self.close_pending = False
                    self.exit_stage = "failed"
                    self.exit_failed.emit("退出偏好保存失败，本次退出已取消。请检查设置后重试。")
                else:
                    self.notify("退出偏好未保存", self.exit_preferences_status.get(), True)
            elif kind == "exit_error":
                value = self.receive_exit_failure(value)
                self.busy = self.cancelable = self.close_pending = False
                self.exit_mode = None
                self.exit_stage = "failed"
                self.startup_active = self.desktop_launch_pending = False
                self.operation.set("未能确认工作区已停止；界面保留，可以重试退出。")
                self.exit_failed.emit(value)
            else:
                self.busy = self.cancelable = False
                self.startup_progress.set(max(0, self.startup_progress.get()))
                if kind == "done":
                    result, done, self.compatible, done_on_exit = value
                    self.operation.set("操作完成")
                    if done and (self.exit_mode is None or done_on_exit):
                        done(result)
                else:
                    self.startup_active = False
                    self.download_progress.set(max(0, self.download_progress.get()))
                    if kind == "startup_error":
                        self.startup_error, value = value
                        self.docker_ready = False
                        self.startup_title.set("需要完成 Docker 准备")
                        self.docker_text.set(value)
                        log.info("docker-check-idle reason=%s", self.startup_error)
                    elif kind == "paused":
                        self.startup_title.set("准备已取消")
                        self.download_title.set("已暂停，可继续")
                    else:
                        self.startup_title.set("操作未完成，可以重试")
                        if self.exit_mode is None:
                            self.notify("操作未完成", value, True)
                    self.operation.set(value)
                    self.startup_detail.set(value)
                    self.download_detail.set(value)
                    lines.append(str(value))
                if self.exit_mode is not None and self.exit_stage == "waiting":
                    self.advance_exit()
            changed = True
        if progress:
            self.update_progress(progress)
        if lines:
            self.log_lines.extend(lines)
            self.log_lines = self.log_lines[-1200:]
            self.logs_added.emit("\n".join(lines))
        if changed:
            self.refresh()
        self._start_pending_recording()
        if self.record_after and not self.resource_inflight and not self.busy and self.exit_mode is None:
            action, self.record_after = self.record_after, None
            action()
        if not self.busy and not self.resource_inflight and self.events.empty():
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
            if self.desktop_launch_pending and self.exit_mode is None:
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

    def check_docker(self, auto_start=False):
        if self.busy or self.exit_mode is not None:
            return
        self.startup_active, self.startup_error = True, None
        log.info("docker-check-start auto-start=%s", auto_start)
        def done(result):
            self.prepared(result)
            log.info("docker-check-ready runtime=%s", self.runtime_ok)
        self.run(lambda engine: prepare_workspace(engine, progress=self.preparation_progress, cancel=self.cancel, auto_start=auto_start, install=False, check=False), done, True)

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
        if self.busy or self.exit_mode is not None or not self.consent_stop():
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
        if not self.workspace_selection_matches():
            self.page_requested.emit("workspace")
            self.notify("先应用身份与目录授权", "请在项目工作区应用所选身份和只读/读写权限，再检查并确认连接。不会继承其它身份的账号。")
            return
        if not self.settings_match():
            self.page_requested.emit("connection")
            return
        path = self.project.get().strip()
        if path:
            title = {"claude": "Claude Code", "codex": "Codex", "shell": "Linux 终端", "login-claude": "Claude Code 登录", "login-codex": "Codex 登录"}.get(tool, tool)
            expected = (self.workspace_profile.get(), self.workspace_access.get())
            self.run(lambda engine: engine.terminal(path, tool, expected_workspace=expected), description=f"正在启动 {title}，后台检查进行中时会自动等待…")
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
        if self.record_active.get():
            self.record_after = lambda: self._migrate_data(target)
            self.stop_resource_recording("storage_change")
            self.operation.set("等待性能记录收尾，再检查数据迁移…")
            return
        self._migrate_data(target)

    def _migrate_data(self, target):
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
                self.resource_epoch += 1
                self.resource_monitor = None
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
            self.run(move, done, done_on_exit=True)
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
        def done(result):
            self.docker_move_status.set("迁移计划已保存。请在 Docker Desktop 的 Disk image location 选择 " + result["target"] + "，完成后回来核验。")
            self.open_docker()
        self.run(lambda engine: prepare_docker_move(engine, target), done)

    def open_docker(self):
        def action(engine):
            path = engine.docker.desktop_app(engine.docker.executable)
            if path is None:
                raise SPXError("未找到 Docker Desktop，请先安装或修复。")
            process = subprocess.Popen([str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=engine.docker.environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            threading.Thread(target=process.wait, daemon=True).start()
        self.run(action, lambda result: self.operation.set("已打开 Docker Desktop，完成设置后回到工作台核验。"))

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
        try:
            result = diagnostics(self.store, self.last_docker_info, self.startup_error)
        except (SPXError, OSError, ValueError, TypeError, AttributeError):
            # A broken setting must not turn Copy diagnostics into another
            # error popup. This path never calls Docker or reads raw log text.
            result = {"app": "ENGE SPX", "version": __version__, "summary": "unavailable"}
        result.update(theme="warm-clay", window_frame="qt-native")
        if self.exit_diagnostics is not None:
            result["last_exit"] = self.exit_diagnostics
        return json.dumps(result, ensure_ascii=False, indent=2)

    def exit_failure(self, error, checks, stage):
        report = failure_report(stage, checks, error, self.exit_workspace_stopped)
        try:
            self.store.write("logs/exit-diagnostics.json", report)
        except (SPXError, OSError):
            log.info("gui-exit-diagnostics-save unavailable")
        return {"message": self.clean_message(error), "report": report}

    def receive_exit_failure(self, value):
        if isinstance(value, dict) and isinstance(value.get("report"), dict):
            self.exit_diagnostics = value["report"]
            return value["message"]
        return value

    def request_close(self):
        log.info("gui-close-requested busy=%s", self.busy)
        self.request_exit("stop")
        return False

    def save_exit_preferences(self):
        """Persist public preferences without constructing/decrypting an Engine."""
        if self.busy or self.exit_mode is not None:
            return False
        enabled, store = self.close_docker_desktop.get(), self.store
        self.busy, self.cancelable = True, False
        self.operation.set("正在保存退出偏好…")
        self.refresh()
        def saved(value):
            self.saved_close_desktop = value
            self.exit_preferences_status.set("退出偏好已保存：真正退出时一起关闭 Docker Desktop。" if value else "退出偏好已保存：退出 ENGE SPX 后保留 Docker Desktop。")
        def worker():
            try:
                result = save_exit_preference(store, enabled)
                # Even a queued exit must observe a successfully saved choice.
                self.events.put(("done", (result, saved, self.compatible, True)))
            except Exception:
                self.events.put(("exit_preferences_error", None))
        self.delivery.start()
        threading.Thread(target=worker, name="spx-exit-preferences", daemon=True).start()
        return True

    def request_exit(self, mode="stop", *, skip_desktop=False):
        if mode not in ("stop", "keep") or self.exit_mode is not None:
            return False
        if mode == "keep" and not self.ask("仅退出界面", "工作区和安全监测若正在运行，将继续留在后台并占用资源，托盘图标也会关闭。需要重新打开软件才能管理。\n\n确认保留工作区，仅退出界面？"):
            return False
        self.exit_mode, self.exit_stage = mode, "waiting"
        self.exit_desktop_done = False
        self.exit_close_desktop = False
        self.exit_skip_desktop = skip_desktop
        self.exit_diagnostics = None
        self.record_after = None
        self.stop_resource_recording("app_exit")
        self.startup_active = self.desktop_launch_pending = False
        self.close_pending = True
        self.set_resource_visible(False)
        self.resource_cancel.set()
        log.info("gui-exit-requested mode=%s busy=%s cancelable=%s", mode, self.busy, self.cancelable)
        if self.busy:
            if self.cancelable:
                self.cancel.set()
                self.operation.set("正在安全取消当前准备，已有进度会保留，随后退出…")
            else:
                self.operation.set("等待当前操作安全完成，随后退出…")
        else:
            self.advance_exit()
        self.refresh()
        return True

    def exit_without_desktop_once(self):
        """A recovery choice, never a persisted setting or unverified workspace exit."""
        if self.busy or self.exit_mode is not None or self.exit_stage != "failed" or not self.exit_workspace_stopped or self.exit_docker is None:
            return False
        try:
            state = self.store.read("runtime.json", {})
            if not isinstance(state, dict) or state.get("phase") != "stopped":
                raise SPXError("工作区状态已改变，请重新执行正常退出。")
        except (SPXError, OSError):
            self.exit_workspace_stopped = False
            self.exit_docker = None
            self.notify("请重新停止工作区", "工作区状态已改变或暂不可读，不能沿用先前的停止结果。请重试正常退出。", True)
            return False
        return self.request_exit("stop", skip_desktop=True)

    def advance_exit(self):
        if self.busy or self.exit_mode is None:
            return
        if self.exit_mode == "keep":
            self.exit_stage = "finalizing"
            self.finish_exit_when_quiet()
            return
        self.exit_close_desktop = self.desktop_exit_supported and self.saved_close_desktop and not self.exit_skip_desktop
        # Desktop may already have closed before a status query failed. Keep
        # the verified result while no further Engine work has occurred; do not
        # require starting Docker again merely to retry or disable joint exit.
        try:
            runtime = self.store.read("runtime.json", {})
            still_stopped = isinstance(runtime, dict) and runtime.get("phase", "stopped") == "stopped"
        except SPXError:
            still_stopped = False
        if self.exit_workspace_stopped and self.exit_docker is not None and still_stopped:
            self.exit_stage = "finalizing"
            self.finish_exit_when_quiet()
            return
        self.exit_workspace_stopped = False
        self.exit_docker = None
        self.exit_stage = "stopping"
        self.busy, self.cancelable = True, False
        self.operation.set("正在停止本实例工作区并退出…")
        def worker(checks):
            def progress(text):
                cleaned = self.clean_message(text)
                log.info("gui-exit-progress %s", cleaned)
                self.events.put(("exit_progress", cleaned))
            try:
                log.info("gui-exit-worker-start")
                try:
                    engine = Engine(self.store, progress)
                except SPXError:
                    context = self.store.read("controller-context.json", {})
                    if context.get("instance") != self.store.instance or not context.get("context"):
                        raise
                    engine = Engine(self.store, progress, stop_context=context["context"])
                    # Exit must validate local IPC without needing a live daemon.
                    from ..docker_env import require_local_context
                    require_local_context(engine.docker)
                log.info("gui-exit-engine-ready")
                result = engine.shutdown()
                if not isinstance(result, dict) or result.get("workspace_stopped") is not True or result.get("background_stopped") is not True:
                    raise SPXError("未能取得完整的工作区与后台停止结果，界面会保留。")
                self.events.put(("exit_done", (result, engine.docker)))
            except Exception as error:
                if self.report:
                    self.report.capture("gui-exit-error", type(error), error, error.__traceback__)
                self.events.put(("exit_error", self.exit_failure(error, checks, "workspace")))
        def tracked_worker():
            with capture_checks() as checks:
                worker(checks)
        self.delivery.start()
        threading.Thread(target=tracked_worker, name="spx-shutdown", daemon=True).start()
        self.refresh()

    def finish_exit_when_quiet(self):
        if self.resource_inflight:
            self.operation.set("正在结束资源采样，随后关闭界面…")
            self.delivery.start()
            return
        if self.exit_mode == "stop" and self.exit_close_desktop and not self.exit_desktop_done:
            if self.exit_stage != "desktop_stopping":
                self.exit_stage = "desktop_stopping"
                self.busy, self.cancelable = True, False
                self.operation.set("工作区与记录已收尾，正在关闭 Docker Desktop…")
                def worker(checks):
                    try:
                        result = stop_desktop(self.exit_docker, lambda text: self.events.put(("exit_progress", text)))
                        if result.get("docker_desktop_stopped") is not True:
                            raise SPXError("未取得 Docker Desktop 的完整停止结果。")
                        self.events.put(("desktop_exit_done", result))
                    except Exception as error:
                        self.events.put(("desktop_exit_error", self.exit_failure(error, checks, "desktop")))
                def tracked_worker():
                    with capture_checks() as checks:
                        worker(checks)
                self.delivery.start()
                threading.Thread(target=tracked_worker, name="spx-desktop-stop", daemon=True).start()
                self.refresh()
            return
        if self.exit_stage != "closing":
            self.exit_stage = "closing"
            log.info("gui-exit-complete mode=%s desktop-stopped=%s desktop-wait-skipped=%s", self.exit_mode, self.exit_desktop_done, self.exit_skip_desktop)
            self.close_requested.emit()

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
            if self.exit_mode is not None:
                ready = False
                title = "正在停止工作区并退出" if self.exit_mode == "stop" else "正在退出界面，保留工作区"
                detail = self.operation.get()
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
            exiting = self.exit_mode is not None
            view = dict(title=title, detail=detail, ready=ready, matching=matching, busy=self.busy or exiting, cancelable=self.cancelable and not self.cancel.is_set() and not exiting, next_text=next_text, steps=tuple(self.steps), route=route, line_status=line_status,
                        ip=evidence.get("ip", "—"), line_ip=evidence.get("line_ip", "—"), region=evidence.get("country", "—") + " / " + evidence.get("city", "—"), timezone=self.timezone.get(),
                        badge="正在退出" if exiting else "工作区已就绪" if ready else "正在准备" if self.busy else "等待确认" if state["phase"] == "review" else "尚未启用",
                        can_confirm=not self.busy and self.docker_ready and state["phase"] == "review" and matching)
            if view != self.view:
                self.view = view
                self.changed.emit(view)
        except Exception as error:
            if self.report:
                self.report.capture("gui-refresh-error", type(error), error, error.__traceback__)
            self.operation.set("状态暂不可用，请查看诊断日志。")
