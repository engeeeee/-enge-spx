"""One coherent desktop shell, with lazily created native pages."""
import json
import os
from pathlib import Path
import webbrowser

from PySide6.QtCore import Qt, QSize, Signal, QEvent, QTimer
from PySide6.QtGui import QIcon, QFont, QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel,
                             QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
                             QPushButton, QPlainTextEdit, QFileDialog, QLineEdit,
                             QSizePolicy, QSizeGrip, QBoxLayout, QSystemTrayIcon, QMenu)

from .. import __version__, terminal
from ..brand import APP_NAME, ICONS, PROJECT_URL
from ..line_security import LINE_MODES
from ..platform_ui import restore_message
from ..proxy import protocol
from ..resource_limits import ROLES, MIN_MEMORY
from ..state import SPXError
from ..storage import DOCKER_STORAGE_DOC
from . import style
from .controller import Value
from .widgets import (Page, Panel, TitleBar, Dialog, Combo, label, bind_text,
                      button, entry, combo, check, progress, confirm, notice, budget_number)

NAMES = {"overview": "工作台", "connection": "连接与代理", "workspace": "项目工作区", "network": "网络检查", "downloads": "下载与安装", "resources": "资源与性能", "logs": "运行日志", "settings": "偏好设置"}


class ResizeEdge(QWidget):
    def __init__(self, parent, edges, cursor):
        super().__init__(parent)
        self.edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self.edges)


class Window(QMainWindow):
    closed = Signal()

    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.c = controller
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ICONS / "app.ico")))
        self.setMinimumSize(700, 480)
        self.resize(1220, 860)
        self.pages, self.nav, self.action_widgets, self.node_boxes = {}, {}, [], []
        self.current_page = None
        self.resource_view = "usage"
        self.resource_panels, self.resource_view_buttons = {}, {}
        self.render_count = 0
        self.log_view = None
        self._last_view = None
        self._force_close = False
        self.tray = None
        self.tray_hint_shown = False
        self._restore_message = restore_message()
        self.exit_buttons = []
        self.exit_action = QAction("退出软件（停止工作区）", self)
        self.exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.exit_action.triggered.connect(self.stop_and_exit)
        self.addAction(self.exit_action)
        self.compact = None
        self.minimized_by_user = False
        self.resize_edges = []
        shell = QFrame()
        shell.setObjectName("Shell")
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.titlebar = TitleBar(self)
        self.titlebar.controls["minimize"].clicked.disconnect()
        self.titlebar.controls["minimize"].clicked.connect(self.minimize)
        outer.addWidget(self.titlebar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(224)
        side = QVBoxLayout(self.sidebar)
        self.side_layout = side
        self.group_labels = []
        side.setContentsMargins(16, 27, 16, 20)
        side.setSpacing(7)
        brand = QHBoxLayout()
        brand.setContentsMargins(8, 0, 4, 20)
        brand.setSpacing(11)
        mark = QLabel()
        mark.setPixmap(QIcon(str(ICONS / "logo-64.png")).pixmap(QSize(32, 32)))
        mark.setFixedSize(32, 32)
        brand.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(3)
        self.brand_label = label(APP_NAME, "Brand")
        self.brand_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        names.addWidget(self.brand_label)
        self.brand_subtitle = label("AI 编程隔离工作台", "Caption")
        names.addWidget(self.brand_subtitle)
        brand.addLayout(names)
        side.addLayout(brand)
        # The minimum comes from actual font metrics in logical pixels. Windows
        # scaling therefore cannot crop the product name between its neighbors.
        self.expanded_sidebar_width = max(224, self.brand_label.sizeHint().width() + 16 * 2 + 32 + 11 + 16)
        self.sidebar.setFixedWidth(self.expanded_sidebar_width)
        for key, name in NAMES.items():
            if key in ("overview", "downloads"):
                heading = label("工作空间" if key == "overview" else "管理", "Caption")
                heading.setContentsMargins(13, 12 if key == "overview" else 23, 0, 6)
                side.addWidget(heading)
                self.group_labels.append(heading)
            nav = button("  " + name, lambda page=key: self.show_page(page))
            nav.setObjectName("Nav")
            nav.setCheckable(True)
            nav.setIcon(style.icon(key))
            nav.setIconSize(QSize(18, 18))
            nav.setToolTip(name)
            nav.setAccessibleName(name)
            side.addWidget(nav)
            self.nav[key] = nav
        side.addStretch()
        footer = QVBoxLayout()
        footer.setContentsMargins(12, 12, 0, 0)
        footer.setSpacing(8)
        self.footer_labels = [label("●  本地隔离工作台", "Muted"), label(f"ENGE SPX  {__version__} Preview", "Caption")]
        for item in self.footer_labels:
            footer.addWidget(item)
        side.addLayout(footer)
        body.addWidget(self.sidebar)
        main = QVBoxLayout()
        main.setSpacing(0)
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        status = QWidget()
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(28, 7, 14, 10)
        self.operation = bind_text(label(kind="Caption"), self.c.operation)
        self.operation.setWordWrap(True)
        status_layout.addWidget(self.operation, 1)
        status_layout.addWidget(QSizeGrip(self))
        main.addWidget(status)
        body.addLayout(main, 1)
        self._create_edges()
        self.c.ask = lambda title, text: confirm(self, title, text)
        self.c.notice.connect(lambda title, text, error: notice(self, title, text, error))
        self.c.changed.connect(self.render)
        self.c.changed.connect(self.update_exit_actions)
        self.c.exit_failed.connect(self.show_exit_error)
        self.c.nodes_changed.connect(self.refresh_node_boxes)
        self.c.workspace_changed.connect(self.refresh_workspace_profiles)
        self.c.logs_added.connect(self.append_logs)
        self.c.page_requested.connect(self.show_page)
        self.c.proxy_requested.connect(lambda: self.proxy_dialog())
        self.c.close_requested.connect(self.finish_close)
        self.c.activation_requested.connect(self.return_from_desktop)
        self.show_page("overview")
        self.render(self.c.view)
        self.update_compact()
        self.fit_to_screen()

    def action(self, text, action, primary=False, ghost=False, ready=False):
        widget = button(text, action, primary, ghost)
        self.action_widgets.append((widget, ready))
        if self.c.view:
            widget.setEnabled(not self.c.busy and (not ready or self.c.view["ready"]))
        return widget

    def show_page(self, name):
        if name == self.current_page:
            return
        if name not in self.pages:
            builder = getattr(self, "build_" + name)
            self.pages[name] = builder()
            self.stack.addWidget(self.pages[name])
        self.stack.setCurrentWidget(self.pages[name])
        for key, widget in self.nav.items():
            widget.setChecked(key == name)
        self.current_page = name
        self.update_resource_activity()
        self.titlebar.caption.setText((APP_NAME if self.compact else "本机工作空间") + "  /  " + NAMES[name])
        self.render(self.c.view, force=True)

    def build_overview(self):
        page = Page("工作台", "准备工作环境，核对代理出口，继续你的项目。")
        hero = page.panel(hero=True)
        row = hero.row()
        hero_row = row
        text = QVBoxLayout()
        text.setSpacing(9)
        self.hero_badge = label("尚未启用", "Accent")
        self.hero_title = label("", "HeroTitle", True)
        self.hero_detail = label("", "Muted", True)
        text.addWidget(self.hero_badge)
        text.addWidget(self.hero_title)
        text.addWidget(self.hero_detail)
        row.addLayout(text, 1)
        actions = QVBoxLayout()
        actions.setSpacing(8)
        self.next_button = self.action("一键准备环境", self.c.next_step, True)
        self.next_button.setMinimumWidth(140)
        self.next_button.setIcon(style.icon("arrow", "#241A15", 17))
        actions.addWidget(self.next_button)
        self.startup_cancel = button("取消准备", self.c.pause, ghost=True)
        actions.addWidget(self.startup_cancel)
        row.addLayout(actions)
        panel = page.panel("准备工作区", "准备环境、配置路径、核对出口，按顺序完成即可。")
        steps = QGridLayout()
        steps.setHorizontalSpacing(12)
        steps.setVerticalSpacing(14)
        panel.layout.addLayout(steps)
        self.step_labels = []
        step_widgets = []
        for index, title in enumerate(("Docker", "运行环境", "连接检查", "出口确认")):
            item = QWidget()
            group = QVBoxLayout(item)
            group.setContentsMargins(0, 0, 0, 0)
            group.setSpacing(8)
            heading = QHBoxLayout()
            heading.setSpacing(8)
            number = label(str(index + 1), "StepNumber")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            number.setFixedSize(28, 28)
            heading.addWidget(number)
            heading.addWidget(label(title, "Muted"), 1)
            group.addLayout(heading)
            value = label("等待处理", "Caption", True)
            value.setContentsMargins(36, 0, 0, 0)
            group.addWidget(value)
            steps.addWidget(item, 0, index)
            steps.setColumnStretch(index, 1)
            step_widgets.append(item)
            self.step_labels.append(value)
        panel.layout.addSpacing(2)
        panel.layout.addWidget(progress(self.c.startup_progress))
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.startup_detail))
        row = panel.row()
        row.addWidget(self.action("查看下载与安装", lambda: self.show_page("downloads"), ghost=True))
        startup_links = row
        row.addWidget(self.action("配置线路与落地", lambda: self.show_page("connection"), ghost=True))
        row.addStretch()
        row.addWidget(self.action("使用说明 ↗", self.c.help, ghost=True))
        metrics = QGridLayout()
        metrics.setSpacing(14)
        self.metric_labels = {}
        metric_widgets = []
        for key, title in (("line_ip", "线路出口"), ("ip", "落地出口"), ("region", "预计地区"), ("timezone", "环境时区")):
            box = Panel()
            box.layout.setContentsMargins(16, 16, 16, 16)
            box.layout.setSpacing(9)
            box.layout.addWidget(label(title, "Caption"))
            value = label("—", "Metric" if key in ("ip", "line_ip") else "Muted", True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.layout.addWidget(value)
            metrics.addWidget(box, 0, len(metric_widgets))
            metrics.setColumnStretch(len(metric_widgets), 1)
            metric_widgets.append(box)
            self.metric_labels[key] = value
        page.layout.addLayout(metrics)
        route = page.panel("工作区网络路径")
        self.route_label = label("", wrap=True)
        self.line_status = label("", "Muted", True)
        route.layout.addWidget(self.route_label)
        route.layout.addWidget(self.line_status)
        row = route.row()
        row.addWidget(self.action("打开项目工作区", lambda: self.show_page("workspace")))
        row.addStretch()
        hint = label("项目保存在本机，工具运行在容器内。", "Caption", True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(hint, 1)
        density = None
        def adapt(width, height):
            nonlocal density
            columns = 4 if width >= 760 else 2 if width >= 440 else 1
            step_columns = 4 if width >= 660 else 2
            new_density = columns, step_columns, width < 540, height < 440
            if density == new_density:
                return
            density = new_density
            for grid, widgets, count in ((metrics, metric_widgets, columns), (steps, step_widgets, step_columns)):
                for item in widgets:
                    grid.removeWidget(item)
                for column in range(4):
                    grid.setColumnStretch(column, 0)
                for index, item in enumerate(widgets):
                    grid.addWidget(item, index // count, index % count)
                    grid.setColumnStretch(index % count, 1)
            hero_row.setDirection(QBoxLayout.Direction.TopToBottom if width < 540 else QBoxLayout.Direction.LeftToRight)
            startup_links.setDirection(QBoxLayout.Direction.TopToBottom if width < 540 else QBoxLayout.Direction.LeftToRight)
            page.subtitle.setVisible(height >= 440)
        page.resized.connect(adapt)
        page.finish()
        return page

    def node_combo(self, value, line=False):
        widget = Combo()
        widget.setMinimumWidth(120)
        self.node_boxes.append((widget, value, line))
        widget.currentIndexChanged.connect(lambda index: value.set(widget.itemData(index) or "") if index >= 0 else None)
        value.changed.connect(lambda selected: widget.setCurrentIndex(widget.findData(selected)))
        self.refresh_node_boxes()
        return widget

    def refresh_node_boxes(self):
        for widget, value, line in self.node_boxes:
            widget.blockSignals(True)
            widget.clear()
            widget.addItem("选择线路节点" if line else "选择落地代理", "")
            for node in self.c.nodes:
                widget.addItem(f"{protocol(node)}  ·  {node['label']}", node["id"])
            widget.setCurrentIndex(max(0, widget.findData(value.get())))
            widget.blockSignals(False)

    def build_connection(self):
        page = Page("连接与代理", "分别选择前置线路与落地，清楚掌握工作区的网络路径。")
        panel = page.panel("落地代理", "支持 SOCKS5、HTTP、HTTPS，也可以导入已有链接和订阅。")
        row = panel.row()
        row.addWidget(self.node_combo(self.c.selected), 1)
        row.addWidget(self.action("添加代理", self.proxy_dialog, True))
        row.addWidget(self.action("批量导入", self.import_dialog))
        row.addWidget(self.action("删除所选代理", self.c.delete_selected_node, ghost=True))
        panel.layout.addWidget(label("代理配置使用 Windows 当前账户加密；跨盘迁移保留，换电脑前请阅读凭据迁移说明。" if self.c.store.credentials.enabled else "此系统使用私有文件权限保存代理配置，未使用 Windows DPAPI 加密。", "Muted"))
        panel = page.panel("前置线路", "已有 v2ray 可作为本机前置，也可在软件内组合固定加密线路与落地。")
        panel.layout.addWidget(check("启用前置线路", self.c.relay_enabled))
        mode = combo(self.c.line_mode, list(LINE_MODES.items()))
        panel.field("接入方式", mode)
        panel.field("软件内双跳的线路节点", self.node_combo(self.c.line_selected, True), "从 v2ray 复制受支持的线路分享链接，使用上方批量导入。")
        panel.field("线路服务器 IPv4", entry(self.c.line_server_ip, "线路地址为域名时填写"), "保留 TLS 名称和证书校验，避免通过本机 DNS 解析线路域名。")
        row = QHBoxLayout()
        row.addWidget(entry(self.c.relay_url, "http://127.0.0.1:10809 或 socks5://127.0.0.1:10808"), 1)
        row.addWidget(self.action("读取系统代理", self.c.read_system_proxy))
        panel.layout.addWidget(label("本机回环代理 · v2ray 兼容与下载使用", "Muted"))
        panel.layout.addLayout(row)
        panel.field("锁定线路出口 IPv4 · 可选", entry(self.c.line_expected_ip, "留空时，确认连接后锁定测得的出口"))
        panel.layout.addWidget(check("下载运行环境与订阅时使用本机代理", self.c.relay_downloads))
        panel.layout.addWidget(label("代理不可用时停止下载；主动取消勾选才使用直连。", "Caption", True))
        row = panel.row()
        row.addWidget(self.action("导出 v2rayN 路由规则", self.export_v2ray, ghost=True))
        row.addStretch()
        panel = page.panel("核对并启用", "检查会停止当前工作环境。请先保存项目，再核对实际出口。")
        self.connection_route = label("", wrap=True)
        self.connection_status = label("", "Muted", True)
        panel.layout.addWidget(self.connection_route)
        panel.layout.addWidget(self.connection_status)
        row = panel.row()
        row.addWidget(self.action("保存设置", self.c.save_settings))
        row.addWidget(self.action("检查连接", self.c.prepare))
        self.confirm_button = self.action("核对并确认", self.c.confirm, True)
        row.addWidget(self.confirm_button)
        row.addStretch()
        row.addWidget(self.action("停止环境", lambda: self.c.run(lambda engine: engine.stop()), ghost=True))
        page.finish()
        return page

    def build_workspace(self):
        page = Page("项目工作区", "使用熟悉的终端，让工具在独立 Linux 环境中继续你的项目。")
        responsive_rows = []
        panel = page.panel("选择项目", "只共享选中的目录，可显式授予只读或读写权限。")
        row = panel.row()
        responsive_rows.append(row)
        self.project_box = entry(self.c.project, "选择一个具体项目文件夹")
        row.addWidget(self.project_box, 1)
        row.addWidget(self.action("选择文件夹", self.choose_project))
        projects = self.c.store.settings()["projects"]
        if projects:
            recent = Combo()
            recent.addItem("最近使用的项目", "")
            for item in reversed(projects):
                recent.addItem(item, item)
            recent.currentIndexChanged.connect(lambda index: self.c.project.set(recent.itemData(index)) if index > 0 else None)
            panel.layout.addWidget(recent)
        panel = page.panel("工作区身份与目录权限", "新身份从空白账号和浏览器资料开始。应用会先停止当前环境，需要重新检查并确认连接。")
        row = panel.row()
        responsive_rows.append(row)
        self.workspace_profile_box = Combo()
        self.workspace_profile_box.setSizeAdjustPolicy(Combo.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.workspace_profile_box.setMinimumContentsLength(12)
        row.addWidget(self.workspace_profile_box, 1)
        row.addWidget(self.action("新建身份", self.new_workspace_profile))
        self.refresh_workspace_profiles()
        self.workspace_profile_box.currentIndexChanged.connect(lambda index: self.c.workspace_profile.set(self.workspace_profile_box.itemData(index)) if index >= 0 else None)
        self.c.workspace_profile.changed.connect(lambda unused: self.sync_workspace_profile())
        row = panel.row()
        responsive_rows.append(row)
        row.addWidget(combo(self.c.workspace_access, [("只读项目", "ro"), ("读写项目", "rw")]), 1)
        self.workspace_apply_button = self.action("应用身份与授权", self.c.apply_workspace, True)
        row.addWidget(self.workspace_apply_button)
        row.addWidget(self.action("恢复上次", lambda: self.c.apply_workspace(restore=True), ghost=True))
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.workspace_status))
        panel.layout.addWidget(label("只读限制项目文件，登录与临时数据仍可保存。切换项目不会自动复制账号；原共享身份保持兼容。", "Caption", True))
        panel = page.panel("打开你的工具", "使用已应用的身份与目录权限，账号和授权会话按身份保留。")
        row = panel.row()
        responsive_rows.append(row)
        for title, tool in (("Claude Code", "claude"), ("Codex", "codex"), ("Linux 终端", "shell")):
            row.addWidget(self.action(title + "  ↗", lambda command=tool: self.open_tool(command), tool == "claude", ready=True))
        row.addStretch()
        self.terminal_hint = label("", "Muted", True)
        panel.layout.addWidget(self.terminal_hint)
        self.c.terminal_kind.changed.connect(lambda unused: self.update_terminal_hint())
        self.update_terminal_hint()
        panel.layout.addWidget(self.action("更换工作区终端", lambda: self.show_page("settings"), ghost=True), alignment=Qt.AlignmentFlag.AlignLeft)
        panel = page.panel("账号与工作区浏览器", "登录页面使用当前身份的 Chromium，与其它身份及本机浏览器资料分开。")
        row = panel.row()
        responsive_rows.append(row)
        row.addWidget(self.action("登录 Claude Code", lambda: self.open_tool("login-claude"), ready=True))
        row.addWidget(self.action("登录 Codex", lambda: self.open_tool("login-codex"), ready=True))
        row.addStretch()
        row.addWidget(self.action("打开 Chromium ↗", self.c.open_workspace_browser, ready=True))
        row = panel.row()
        responsive_rows.append(row)
        row.addWidget(self.action("停止浏览器 · 保留 CLI", lambda: self.c.run(lambda engine: engine.stop_browser()), ghost=True))
        row.addWidget(self.action("资源与浏览器启动设置", lambda: self.show_page("resources"), ghost=True))
        row.addStretch()
        previous_narrow = None
        def adapt(width, height):
            nonlocal previous_narrow
            narrow = width < 550
            if narrow != previous_narrow:
                previous_narrow = narrow
                for layout in responsive_rows:
                    layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        page.resized.connect(adapt)
        adapt(page.viewport().width(), page.viewport().height())
        page.finish()
        return page

    def refresh_workspace_profiles(self):
        if not hasattr(self, "workspace_profile_box"):
            return
        box = self.workspace_profile_box
        box.blockSignals(True)
        box.clear()
        if self.c.workspace_config:
            for identity, name in self.c.workspace_config["profiles"].items():
                box.addItem(name, identity)
        else:
            box.addItem("身份配置不可用，请恢复", "")
        box.blockSignals(False)
        self.sync_workspace_profile()

    def sync_workspace_profile(self):
        if hasattr(self, "workspace_profile_box"):
            box = self.workspace_profile_box
            box.blockSignals(True)
            box.setCurrentIndex(box.findData(self.c.workspace_profile.get()))
            box.blockSignals(False)

    def new_workspace_profile(self):
        dialog = Dialog(self, "新建空白身份")
        dialog.body.addWidget(label("新身份不会复制旧账号、Cookie 或浏览器资料。创建后仍需应用到项目并重新登录。", "Muted", True))
        name = QLineEdit()
        name.setMaxLength(64)
        name.setPlaceholderText("例如：个人项目、独立测试")
        dialog.body.addWidget(name)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("取消", dialog.reject, ghost=True))
        def create():
            if self.c.create_workspace(name.text()):
                dialog.accept()
        row.addWidget(button("创建空白身份", create, True))
        dialog.body.addLayout(row)
        dialog.exec()

    def build_resources(self):
        page = Page("资源与性能", "查看占用来源，为工作区安排预算；安全监测始终独立运行。")
        self.resource_panels = {"usage": [], "budget": [], "record": []}
        row = QHBoxLayout()
        for key, title in (("usage", "占用概览"), ("budget", "预算设置"), ("record", "实机记录")):
            item = button(title, lambda value=key: self.select_resource_view(value))
            item.setCheckable(True)
            self.resource_view_buttons[key] = item
            row.addWidget(item)
        row.addStretch()
        page.layout.addLayout(row)
        def section(group, *args):
            result = page.panel(*args)
            self.resource_panels[group].append(result)
            return result
        panel = section("budget")
        row = panel.row()
        budget_actions = row
        self.resource_save_button = self.action("保存资源设置", self.c.save_resources, True)
        row.addWidget(self.resource_save_button)
        row.addWidget(self.action("恢复上次设置", lambda: self.c.save_resources(True)))
        row.addStretch()
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.resource_status))
        panel = section("budget", "资源预算", "正常模式沿用原有上限；低资源模式限制 CPU、减少内存，并默认按需打开浏览器。")
        panel.field("工作模式", combo(self.c.resource_mode, [("正常 · 沿用现有预算", "normal"), ("低资源", "low"), ("自定义", "custom")]))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        budget_headers, budget_rows = [], []
        for column, text in enumerate(("工作环境", "CPU 上限", "内存上限")):
            heading = label(text, "Muted")
            budget_headers.append(heading)
            grid.addWidget(heading, 0, column)
        for index, (role, title) in enumerate(ROLES.items(), 1):
            title_widget = label(title)
            grid.addWidget(title_widget, index, 0)
            fields = []
            for column, suffix, cpu in ((1, "_cpu", True), (2, "_memory", False)):
                widget = budget_number(self.c.values["budget_" + role + suffix], cpu, 0 if role == "gateway" else MIN_MEMORY[role])
                widget.setAccessibleName(title + (" CPU 上限" if cpu else "内存上限"))
                grid.addWidget(widget, index, column)
                fields.append(widget)
            budget_rows.append((title_widget, *fields, label("CPU 上限", "Muted"), label("内存上限", "Muted")))
        panel.layout.addLayout(grid)
        panel.layout.addWidget(label("CPU 0 表示不限；网关内存可设为不限，其它容器使用有效内存上限。上限不是预留量，多项目预算会累加。内存与交换合计最多为所设内存的两倍（内核支持时）。", "Caption", True))
        panel.layout.addWidget(check("随工具启动浏览器", self.c.auto_browser))
        panel.layout.addWidget(label("关闭此项后仍可单独打开 Chromium；显式点击登录会准备浏览器，不会回退到本机浏览器。", "Caption", True))
        panel = section("budget", "当前项目的独立预算", "先在项目工作区选择目录；未单独设置的项目沿用上方 CLI 预算。")
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.project))
        panel.layout.addWidget(check("启用独立项目预算", self.c.project_budget_enabled))
        row = panel.row()
        project_inputs = row
        for value, cpu, title in ((self.c.project_budget_cpu, True, "项目 CPU 上限"), (self.c.project_budget_memory, False, "项目内存上限")):
            widget = budget_number(value, cpu, MIN_MEMORY["project"])
            widget.setAccessibleName(title)
            widget.setEnabled(self.c.project_budget_enabled.get())
            self.c.project_budget_enabled.changed.connect(widget.setEnabled)
            row.addWidget(widget)
        row.addStretch()
        panel = section("usage", "应用进程", "界面和已登记的后台服务，工作集可能包含共享页；短时 Docker CLI 不列入此处。")
        panel.layout.addWidget(bind_text(label(wrap=True), self.c.resource_app_text))
        panel = section("usage", "本实例的 Linux 容器", "Docker CLI 内存读数已扣除部分文件缓存；磁盘 I/O 是累计值，不是实时带宽。")
        panel.layout.addWidget(bind_text(label(wrap=True), self.c.resource_container_text))
        panel = section("usage", "主机与虚拟机", "Docker Desktop 与 WSL2 分别展示。WSL2 包含容器和其它发行版，不能与容器内存相加。停止环境不等于 WSL2 立即归还所有缓存。")
        panel.layout.addWidget(bind_text(label(wrap=True), self.c.resource_system_text))
        panel.layout.addWidget(bind_text(label(kind="Caption", wrap=True), self.c.resource_caption))
        row = panel.row()
        monitor_actions = row
        row.addWidget(button("立即采样", self.c.sample_resources))
        row.addWidget(self.action("停止本工作区", lambda: self.c.run(lambda engine: engine.stop()), ghost=True))
        row.addStretch()
        panel = section("record", "实机性能记录", "手动记录真实使用期间的占用；记录中可以继续操作工作区，最小化/托盘中也会继续。停止或真正退出时保存，安全监测保持运行。")
        from ..resource_recording import ACTIVITIES
        self.record_duration = combo(self.c.record_seconds, [("1 分钟", 60), ("5 分钟", 300), ("15 分钟", 900), ("60 分钟", 3600)])
        self.record_activity = combo(self.c.record_activity, [(title, key) for key, title in ACTIVITIES.items()])
        panel.field("记录时长", self.record_duration)
        panel.field("本次活动（自己选择）", self.record_activity)
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.record_status))
        row = panel.row()
        recording_actions = row
        self.record_start = button("开始记录…", self.start_resource_recording, True)
        self.record_stop = button("停止并保存", self.c.stop_resource_recording)
        self.record_export = button("导出最近结果…", self.export_resource_recording)
        for widget in (self.record_start, self.record_stop, self.record_export):
            row.addWidget(widget)
        row.addStretch()
        self.c.record_active.changed.connect(lambda unused: self.update_recording_controls())
        self.c.record_available.changed.connect(lambda unused: self.update_recording_controls())
        self.update_recording_controls()
        previous_narrow = None
        def adapt(width, height):
            nonlocal previous_narrow
            narrow = width < 550
            if narrow == previous_narrow:
                return
            previous_narrow = narrow
            for layout in (budget_actions, project_inputs, monitor_actions, recording_actions):
                layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
            for widget in [*budget_headers, *(item for row in budget_rows for item in row)]:
                grid.removeWidget(widget)
            for column, widget in enumerate(budget_headers):
                widget.setVisible(not narrow)
                if not narrow:
                    grid.addWidget(widget, 0, column)
            for index, (title, cpu, memory, cpu_label, memory_label) in enumerate(budget_rows):
                cpu_label.setVisible(narrow)
                memory_label.setVisible(narrow)
                if narrow:
                    row = index * 3
                    grid.addWidget(title, row, 0, 1, 2)
                    grid.addWidget(cpu_label, row + 1, 0)
                    grid.addWidget(cpu, row + 1, 1)
                    grid.addWidget(memory_label, row + 2, 0)
                    grid.addWidget(memory, row + 2, 1)
                else:
                    for column, widget in enumerate((title, cpu, memory)):
                        grid.addWidget(widget, index + 1, column)
        page.resized.connect(adapt)
        adapt(page.viewport().width(), page.viewport().height())
        page.finish()
        self.select_resource_view("usage")
        return page

    def update_recording_controls(self):
        if not hasattr(self, "record_start"):
            return
        active = self.c.record_active.get()
        enabled = not self.c.busy and self.c.exit_mode is None
        self.record_start.setEnabled(enabled and not active)
        self.record_stop.setEnabled(active and self.c.exit_mode is None)
        self.record_export.setEnabled(enabled and not active and self.c.record_available.get())
        self.record_duration.setEnabled(enabled and not active)
        self.record_activity.setEnabled(enabled and not active)

    def start_resource_recording(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存脱敏性能记录", "ENGE-SPX-performance.json", "JSON (*.json)")
        if path:
            self.c.start_resource_recording(path)

    def export_resource_recording(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出最近一次性能记录", "ENGE-SPX-performance.json", "JSON (*.json)")
        if path:
            self.c.export_resource_recording(path)

    def build_network(self):
        page = Page("网络环境检查", "按对象查看实际证据，区分已验证、未运行和不可用；不自动更改环境。")
        panel = page.panel("检查当前工作区", "公网检测只在受控容器中执行，宿主只读路由，浏览器不会自动启动。出口复核失败、发现直连或安全条件变化时，会停止本实例并核验结果。")
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.network_summary))
        row = panel.row()
        row.addWidget(self.action("检查网络环境", self.c.check_network, True))
        row.addWidget(self.action("导出脱敏报告", self.save_network_report))
        row.addWidget(self.action("查看时区设置", lambda: self.show_page("settings"), ghost=True))
        panel.layout.addWidget(label("WebRTC 仅观察本地候选与容器回环测试，不代表验证所有公网 STUN/TURN。IP 地区为近似参考，不保证匿名或不会关联账号。", "Caption", True))
        panel = page.panel("检测对象与证据", "宿主、容器、浏览器、第一跳与最终出口分开记录。语言只读；已有环境的时区保持固定。")
        evidence = QPlainTextEdit()
        evidence.setReadOnly(True)
        evidence.setMinimumHeight(320)
        evidence.setPlainText(self.c.network_evidence.get())
        self.c.network_evidence.changed.connect(evidence.setPlainText)
        panel.layout.addWidget(evidence)
        page.resized.connect(lambda width, height: row.setDirection(QBoxLayout.Direction.TopToBottom if width < 550 else QBoxLayout.Direction.LeftToRight))
        page.finish()
        return page

    def save_network_report(self):
        if self.c.network_report is None:
            self.c.notify("先运行检查", "请先生成一份当前工作区的网络检查报告。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出脱敏网络报告", "ENGE-SPX-network-report.json", "JSON (*.json)")
        if path:
            self.c.export_network_report(path)

    def select_resource_view(self, view):
        self.resource_view = view
        for key, panels in self.resource_panels.items():
            for panel in panels:
                panel.setVisible(key == view)
            self.resource_view_buttons[key].setChecked(key == view)
        if "resources" in self.pages:
            self.pages["resources"].verticalScrollBar().setValue(0)
        self.update_resource_activity()

    def build_downloads(self):
        page = Page("下载与安装", "自动准备依赖，查看进度，保留已经完成的下载。")
        panel = page.panel("Docker Desktop", "使用本机 Linux containers / WSL 2 引擎。")
        panel.layout.addWidget(bind_text(label(wrap=True), self.c.docker_text))
        row = panel.row()
        row.addWidget(self.action("重新检测", self.c.check_docker))
        row.addWidget(self.action("启动并检测", lambda: self.c.check_docker(True)))
        row.addStretch()
        row.addWidget(self.action("下载 Docker ↗", lambda: webbrowser.open("https://docs.docker.com/desktop/setup/install/windows-install/"), ghost=True))
        panel = page.panel("运行环境", "首次约 1 GB。已有匹配镜像会复用，导入前自动核验文件。")
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.runtime_text))
        panel.layout.addWidget(bind_text(label(kind="SectionTitle"), self.c.download_title))
        panel.layout.addWidget(progress(self.c.download_progress))
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.download_detail))
        row = panel.row()
        row.addWidget(self.action("下载并安装 / 继续", lambda: self.c.prepare(check=False), True))
        self.pause_button = button("暂停", self.c.pause)
        row.addWidget(self.pause_button)
        row.addStretch()
        panel = page.panel("下载代理", "与工作区的线路模式分别配置，首次安装前即可使用。")
        panel.layout.addWidget(check("使用本机代理下载运行环境与订阅", self.c.relay_downloads))
        row = panel.row()
        row.addWidget(entry(self.c.relay_url, "留空时读取系统回环代理"), 1)
        row.addWidget(self.action("读取系统代理", self.c.read_system_proxy))
        panel.layout.addWidget(label("代理不可用时停止；取消勾选才使用直连。", "Caption", True))
        panel = page.panel("高级方式", "源码构建使用 Docker Desktop 自己的网络设置，可能需要更长时间。")
        panel.layout.addWidget(self.action("从源码构建", lambda: self.c.prepare(check=False, source=True), ghost=True), alignment=Qt.AlignmentFlag.AlignLeft)
        page.finish()
        return page

    def build_logs(self):
        page = Page("运行日志", "查看当前任务的输出；详细安装记录也保存在应用数据目录。")
        panel = page.panel()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1200)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setMinimumHeight(380)
        self.log_view.setPlainText("\n".join(self.c.log_lines))
        panel.layout.addWidget(self.log_view)
        row = panel.row()
        row.addWidget(self.action("打开数据目录", self.open_data))
        row.addWidget(self.action("复制诊断信息", self.copy_diagnostics))
        row.addStretch()
        page.finish()
        return page

    def build_settings(self):
        page = Page("偏好设置", "选择自己的终端，安排数据位置，让工作台适合你的习惯。")
        panel = page.panel("启动行为")
        panel.layout.addWidget(label("打开软件只检测状态，由你决定何时启动 Docker。", wrap=True))
        panel.layout.addWidget(label("点击“一键准备环境”或“启动并检测”才会启动 Docker Desktop。", "Caption", True))
        panel.layout.addWidget(label("关闭窗口后隐藏到系统托盘。托盘右键可恢复窗口、保留工作区退出界面，或停止工作区并退出。", "Caption", True))
        panel.layout.addWidget(label("退出软件（Ctrl+Q）会先停止本实例的 CLI、浏览器、网关与后台服务；默认保留 Docker Desktop。", "Caption", True))
        self.close_desktop_check = check("真正退出时同时关闭 Docker Desktop", self.c.close_docker_desktop)
        panel.layout.addWidget(self.close_desktop_check)
        panel.layout.addWidget(label("会正常关闭 Docker Desktop，其它 Docker 容器也会中断。X 隐藏和“保留工作区退出”不触发；不关闭其它 WSL 发行版。", "Caption", True))
        self.save_exit_preferences_button = self.action("保存退出偏好", self.c.save_exit_preferences, ghost=True)
        panel.layout.addWidget(self.save_exit_preferences_button, alignment=Qt.AlignmentFlag.AlignLeft)
        panel.layout.addWidget(bind_text(label("", "Muted", True), self.c.exit_preferences_status))
        if not self.c.desktop_exit_supported:
            panel.layout.addWidget(label("联合关闭仅支持 Windows Docker Desktop。", "Caption", True))
        self.close_desktop_check.setEnabled(self.c.desktop_exit_supported)
        self.save_exit_preferences_button.setEnabled(self.c.desktop_exit_supported)
        for text, action in (("退出软件（停止工作区）", self.stop_and_exit), ("保留工作区退出界面…", self.exit_interface)):
            item = button(text, action, ghost=True)
            self.exit_buttons.append(item)
            if action == self.stop_and_exit:
                self.stop_exit_button = item
            panel.layout.addWidget(item, alignment=Qt.AlignmentFlag.AlignLeft)
        panel = page.panel("工作区终端", "Windows Terminal、PowerShell 或你选择的自定义终端。")
        panel.field("终端类型", combo(self.c.terminal_kind, list(terminal.PRESETS.items())))
        row = QHBoxLayout()
        self.terminal_path = entry(self.c.terminal_exe, "预设可自动寻找，或选择便携版 exe")
        row.addWidget(self.terminal_path, 1)
        row.addWidget(self.action("选择 exe", self.choose_terminal))
        panel.layout.addWidget(label("终端程序", "Muted"))
        panel.layout.addLayout(row)
        self.terminal_args = panel.field("自定义启动参数", entry(self.c.terminal_args, "按所选终端的说明填写"), "{project} 为项目目录，{title} 为标题，独立的 {command} 插入工作区命令。")
        panel.layout.addWidget(label("自定义终端请关闭会自动输入命令的欢迎页，避免欢迎指令进入工具输入框。", "Caption", True))
        self.c.terminal_kind.changed.connect(lambda unused: self.terminal_fields())
        self.terminal_fields()
        row = panel.row()
        row.addWidget(self.action("检测终端", self.c.detect_terminal))
        row.addWidget(self.action("测试终端", lambda: self.c.terminal_action()))
        row.addWidget(self.action("保存终端", lambda: self.c.terminal_action(True), True))
        row.addStretch()
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.terminal_status))
        panel = page.panel("应用数据与下载缓存", "配置、日志和下载缓存可以迁移到 D 盘等自选目录。")
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.data_location))
        row = panel.row()
        row.addWidget(entry(self.c.data_target, "选择专用的空目标文件夹"), 1)
        row.addWidget(self.action("选择目录", lambda: self.choose_storage(self.c.data_target)))
        row = panel.row()
        row.addWidget(self.action("检查并迁移应用数据", self.c.migrate_data, True))
        row.addWidget(self.action("打开当前目录", self.open_data, ghost=True))
        row.addStretch()
        panel.layout.addWidget(progress(self.c.storage_progress))
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.storage_status))
        panel.layout.addWidget(label("迁移会停止工作区，校验成功后切换位置并清理已校验副本。项目文件仍在原项目目录。", "Caption", True))
        panel = page.panel("Docker 数据盘", "Docker Desktop 负责移动实际磁盘，软件记录资源并帮助核验。")
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.docker_location))
        row = panel.row()
        row.addWidget(entry(self.c.docker_target, "例如 D:\\DockerData"), 1)
        row.addWidget(self.action("选择目录", lambda: self.choose_storage(self.c.docker_target)))
        panel.layout.addWidget(label("1. 检测位置并准备迁移。\n2. 在 Docker Desktop → Resources → Advanced → Disk image location 选择目标并 Apply。\n3. 回到这里核验原镜像、容器和数据卷。", "Caption", True))
        row = panel.row()
        row.addWidget(self.action("检测位置", self.c.detect_storage))
        row.addWidget(self.action("准备迁移", self.c.prepare_docker_move))
        row.addWidget(self.action("核验结果", self.c.verify_docker_move, True))
        row.addStretch()
        panel.layout.addWidget(bind_text(label(kind="Muted", wrap=True), self.c.docker_move_status))
        panel.layout.addWidget(self.action("打开 Docker Desktop ↗", self.c.open_docker, ghost=True), alignment=Qt.AlignmentFlag.AlignLeft)
        panel.layout.addWidget(self.action("Docker 官方迁移说明 ↗", lambda: webbrowser.open(DOCKER_STORAGE_DOC), ghost=True), alignment=Qt.AlignmentFlag.AlignLeft)
        panel = page.panel("环境设置", "已有环境固定时区；不同资料或时区请使用独立数据目录。")
        panel.field("IANA 时区", entry(self.c.timezone))
        panel.field("本机 Docker 上下文", entry(self.c.context))
        panel.layout.addWidget(self.action("保存环境设置", self.c.save_settings, True), alignment=Qt.AlignmentFlag.AlignLeft)
        panel = page.panel("关于 ENGE SPX", "Windows 上的 AI 编程隔离工作台。")
        panel.layout.addWidget(label(f"{__version__} Preview · engeeeee", "Muted"))
        panel.layout.addWidget(label("容器按项目共享文件，账号与浏览器资料会保留。容器不等同于完全隔离的独立电脑。", "Caption", True))
        row = panel.row()
        row.addWidget(self.action("项目仓库 ↗", lambda: webbrowser.open(PROJECT_URL), ghost=True))
        row.addWidget(self.action("复制诊断信息", self.copy_diagnostics, ghost=True))
        row.addStretch()
        page.finish()
        return page

    def render(self, view, force=False):
        if not view or view == self._last_view and not force:
            return
        self._last_view = dict(view)
        self.render_count += 1
        self.hero_title.setText(view["title"])
        self.hero_detail.setText(view["detail"])
        self.hero_badge.setText("●  " + view["badge"])
        if self.next_button.text() != view["next_text"]:
            self.next_button.setText(view["next_text"])
        for widget, needs_ready in self.action_widgets:
            enabled = not view["busy"] and (not needs_ready or view["ready"])
            if widget.isEnabled() != enabled:
                widget.setEnabled(enabled)
        self.update_recording_controls()
        self.update_exit_actions(view)
        for name in ("pause_button", "startup_cancel"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(view["busy"] and view["cancelable"])
        self.startup_cancel.setVisible(view["busy"] and view["cancelable"])
        if hasattr(self, "confirm_button"):
            self.confirm_button.setEnabled(view["can_confirm"])
        for widget, text in zip(self.step_labels, view["steps"]):
            if widget.text() != text:
                widget.setText(text)
        for key, widget in self.metric_labels.items():
            text = self.c.timezone.get() if key == "timezone" else view[key]
            if widget.text() != text:
                widget.setText(text)
        for name, key in (("route_label", "route"), ("line_status", "line_status"), ("connection_route", "route"), ("connection_status", "line_status")):
            if hasattr(self, name) and getattr(self, name).text() != view[key]:
                getattr(self, name).setText(view[key])

    def append_logs(self, text):
        if self.log_view is not None:
            bar = self.log_view.verticalScrollBar()
            follow = bar.value() >= bar.maximum() - 4
            self.log_view.appendPlainText(text)
            if follow:
                bar.setValue(bar.maximum())

    def terminal_fields(self):
        kind = self.c.terminal_kind.get()
        self.terminal_path.setEnabled(kind != "auto")
        self.terminal_args.setEnabled(kind == "custom")

    def update_terminal_hint(self):
        kind = self.c.terminal_kind.get()
        self.terminal_hint.setText("当前终端：" + next((name for name, key in terminal.PRESETS.items() if key == kind), "自定义终端"))

    def choose_project(self):
        value = QFileDialog.getExistingDirectory(self, "选择具体项目文件夹", self.c.project.get())
        if value:
            self.c.project.set(value)

    def open_tool(self, tool):
        if not self.c.project.get().strip():
            self.choose_project()
        if self.c.project.get().strip():
            self.c.open_terminal(tool)

    def choose_storage(self, value):
        path = QFileDialog.getExistingDirectory(self, "选择专用的空目标目录", value.get())
        if path:
            value.set(path)

    def choose_terminal(self):
        path, unused = QFileDialog.getOpenFileName(self, "选择终端程序", self.c.terminal_exe.get(), "Windows 程序 (*.exe);;所有文件 (*)")
        if path:
            self.c.terminal_exe.set(path)
            if self.c.terminal_kind.get() == "auto":
                self.c.terminal_kind.set("custom")

    def export_v2ray(self):
        path, unused = QFileDialog.getSaveFileName(self, "保存 v2rayN 路由规则", "ENGE-SPX-v2rayN-rules.json", "JSON (*.json)")
        if path:
            self.c.export_v2ray(path)

    def open_data(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.c.store.home)))

    def copy_diagnostics(self):
        QApplication.clipboard().setText(self.c.diagnostics())
        self.c.operation.set("已复制诊断摘要，不包含节点凭据、出口 IP 或项目路径。")

    def proxy_dialog(self):
        if not self.c.consent_stop():
            return
        dialog = Dialog(self, "添加落地代理", 540)
        values = {key: Value(value, dialog) for key, value in dict(type="SOCKS5", server="", port="1080", username="", password="", name="").items()}
        for title, key in (("协议", "type"), ("服务器地址", "server"), ("端口", "port"), ("用户名 · 可选", "username"), ("密码 · 可选", "password"), ("名称 · 可选", "name")):
            dialog.body.addWidget(label(title, "Muted"))
            widget = combo(values[key], [(name, name) for name in ("SOCKS5", "HTTP", "HTTPS")]) if key == "type" else entry(values[key], secret=key == "password")
            dialog.body.addWidget(widget)
        values["type"].changed.connect(lambda value: values["port"].set({"SOCKS5": "1080", "HTTP": "80", "HTTPS": "443"}[value]))
        def save():
            try:
                self.c.save_proxy({key: value.get() for key, value in values.items()})
                dialog.accept()
            except SPXError as error:
                notice(dialog, "检查代理信息", str(error))
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", dialog.reject, ghost=True))
        actions.addWidget(button("保存代理", save, True))
        dialog.body.addLayout(actions)
        dialog.exec()

    def import_dialog(self):
        if not self.c.consent_stop():
            return
        dialog = Dialog(self, "导入代理与订阅", 660)
        mode = Value(False, dialog)
        dialog.body.addWidget(combo(mode, [("代理链接 / JSON / Clash", False), ("订阅地址（HTTPS）", True)]))
        dialog.body.addWidget(label("HTTPS 落地代理使用第一项；获取订阅需明确选择第二项。", "Caption", True))
        text = QPlainTextEdit()
        text.setPlaceholderText("粘贴节点链接、配置内容，或 HTTPS 订阅地址…")
        text.setMinimumHeight(230)
        dialog.body.addWidget(text)
        def load():
            path, unused = QFileDialog.getOpenFileName(dialog, "选择节点配置")
            if path:
                try:
                    if Path(path).stat().st_size > 2 * 1024**2:
                        raise ValueError()
                    text.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
                    mode.set(False)
                except (OSError, ValueError):
                    notice(dialog, "读取失败", "请选择小于 2 MiB 的 UTF-8 文件。")
        def accept():
            content = text.toPlainText().strip()
            if not content:
                return
            if self.c.import_nodes(content, mode.get()):
                dialog.accept()
        row = QHBoxLayout()
        row.addWidget(button("选择配置文件", load))
        row.addStretch()
        row.addWidget(button("取消", dialog.reject, ghost=True))
        row.addWidget(button("导入", accept, True))
        dialog.body.addLayout(row)
        dialog.exec()

    def minimize(self):
        self.minimized_by_user = True
        self.showMinimized()

    def fit_to_screen(self):
        area = self.screen().availableGeometry()
        self.setMinimumSize(min(700, max(400, area.width() - 24)), min(480, max(320, area.height() - 24)))
        self.resize(min(1220, area.width() - 24), min(860, area.height() - 24))
        self.move(area.center() - self.rect().center())

    def reveal(self):
        self.minimized_by_user = False
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def nativeEvent(self, event_type, message):
        if self._restore_message and event_type == b"windows_generic_MSG":
            from ctypes import wintypes
            event = wintypes.MSG.from_address(int(message))
            if event.message == self._restore_message:
                # Defer widget changes until the native sender receives its
                # acknowledgement; keep all GUI state changes in Qt's loop.
                QTimer.singleShot(0, self.reveal)
                return True, 1
        return super().nativeEvent(event_type, message)

    def return_from_desktop(self):
        if not self.minimized_by_user:
            self.reveal()

    def finish_close(self):
        self._force_close = True
        self.close()

    def install_tray(self):
        if self.tray is not None or not QSystemTrayIcon.isSystemTrayAvailable():
            return self.tray is not None
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(APP_NAME + " · 工作区控制台")
        self.tray_menu = QMenu(self)
        self.tray_status = self.tray_menu.addAction("工作区状态")
        self.tray_status.setEnabled(False)
        self.tray_menu.addSeparator()
        self.tray_show = self.tray_menu.addAction("显示主窗口", self.reveal)
        self.tray_menu.addSeparator()
        self.tray_stop_exit = self.exit_action
        self.tray_menu.addAction(self.exit_action)
        more = self.tray_menu.addMenu("更多")
        self.tray_exit = more.addAction("保留工作区，仅退出界面…", self.exit_interface)
        self.tray.setContextMenu(self.tray_menu)
        self.titlebar.controls["close"].setToolTip("隐藏到托盘，工作区继续运行")
        self.tray.activated.connect(self.tray_activated)
        self.update_exit_actions(self.c.view)
        self.tray.show()
        return True

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.reveal()

    def exit_interface(self):
        self.reveal()
        self.c.request_exit("keep")

    def stop_and_exit(self):
        self.reveal()
        self.show_page("overview")
        self.c.request_exit("stop")

    def update_exit_actions(self, view):
        pending = self.c.exit_mode is not None
        close_desktop = self.c.desktop_exit_supported and self.c.saved_close_desktop
        text = "退出并关闭 Docker Desktop" if close_desktop else "退出软件（停止工作区）"
        self.exit_action.setText(text)
        if hasattr(self, "stop_exit_button"):
            self.stop_exit_button.setText(text)
        self.exit_action.setEnabled(not pending)
        if hasattr(self, "close_desktop_check"):
            self.close_desktop_check.setEnabled(self.c.desktop_exit_supported and not pending and not self.c.busy)
            self.save_exit_preferences_button.setEnabled(self.c.desktop_exit_supported and not pending and not self.c.busy)
        for item in self.exit_buttons:
            item.setEnabled(not pending)
        if self.tray is not None:
            self.tray_exit.setEnabled(not pending)
            status = view.get("badge", "尚未启用")
            self.tray_status.setText(status)
            self.tray.setToolTip(APP_NAME + " · " + status)

    def show_exit_error(self, message):
        self.reveal()
        self.update_resource_activity()
        detail = "工作区已停止，Docker Desktop 尚未确认退出。可重试，或在设置中取消联合关闭并保存后退出。" if self.c.exit_workspace_stopped else "退出未完成，界面已保留。可以重试“退出软件”，或明确选择保留工作区退出界面。"
        self.c.notify("退出尚未完成", message + "\n\n" + detail, True)

    def closeEvent(self, event):
        if not self._force_close and self.tray is not None and self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            self.minimized_by_user = True
            self.hide()
            if not self.tray_hint_shown and QSystemTrayIcon.supportsMessages():
                self.tray_hint_shown = True
                self.tray.showMessage(APP_NAME, "工作区继续在后台运行。托盘右键“退出软件”会停止工作区并退出。", QSystemTrayIcon.MessageIcon.Information, 4000)
            event.ignore()
            return
        if self._force_close or self.c.request_close():
            self.c.stop_resource_monitor()
            self.c.delivery.stop()
            self.c.status_timer.stop()
            self.c.refresh_timer.stop()
            if self.tray is not None:
                self.tray.hide()
            event.accept()
            self.closed.emit()
        else:
            event.ignore()

    def update_resource_activity(self):
        if not hasattr(self, "c"):
            return
        background = not self.isVisible() or self.isMinimized()
        self.c.set_background(background)
        self.c.set_resource_visible(self.current_page == "resources" and self.resource_view == "usage" and not background)

    def showEvent(self, event):
        super().showEvent(event)
        self.update_resource_activity()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.update_resource_activity()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.update_resource_activity()

    def _create_edges(self):
        for edges, cursor in ((Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor), (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor), (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor), (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor), (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeFDiagCursor), (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.CursorShape.SizeBDiagCursor), (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeBDiagCursor), (Qt.Edge.RightEdge | Qt.Edge.BottomEdge, Qt.CursorShape.SizeFDiagCursor)):
            self.resize_edges.append(ResizeEdge(self, edges, cursor))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "footer_labels"):
            self.update_compact()
        if not self.resize_edges:
            return
        w, h, b = self.width(), self.height(), 5
        positions = [(0, b, b, h-2*b), (w-b, b, b, h-2*b), (b, 0, w-2*b, b), (b, h-b, w-2*b, b), (0, 0, b, b), (w-b, 0, b, b), (0, h-b, b, b), (w-b, h-b, b, b)]
        for edge, position in zip(self.resize_edges, positions):
            edge.setGeometry(*position)
            edge.setVisible(not self.isMaximized())
            edge.raise_()

    def update_compact(self):
        compact = self.width() < 1000
        if compact == self.compact:
            return
        self.compact = compact
        self.sidebar.setFixedWidth(76 if compact else self.expanded_sidebar_width)
        self.side_layout.setContentsMargins(8 if compact else 16, 27, 8 if compact else 16, 20)
        for widget in [self.brand_label, self.brand_subtitle, *self.group_labels, *self.footer_labels]:
            widget.setVisible(not compact)
        for key, widget in self.nav.items():
            widget.setText("" if compact else "  " + NAMES[key])
        self.titlebar.caption.setText((APP_NAME if compact else "本机工作空间") + "  /  " + NAMES.get(self.current_page, "工作台"))
