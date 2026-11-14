# Smart Clipboard 架构与审计

## 现有调用关系与选择

```text
GUI Controller.open_tool
  → Engine.terminal → _tool_session / ready / _project
  → 外部终端或自有终端进程的公共 spx attach 参数
  → Engine.attach_command（guard、session、container、Profile、挂载审计）
  → 智能终端：docker exec -i → Linux PTY relay → tool_session.command → 原有 Claude / Codex TUI
  → 外部终端：docker exec -it → tool_session.command → 原有 TUI
```

原有 `terminal.py` 使用 argv 启动 Windows Terminal、无 Profile 的 PowerShell 或自定义 exe。项目目录 bind 位于 `/workspace/<key>`，账号 home 按 Profile 使用既有卷，项目容器与浏览器分开，`attach` 拒绝过期会话。上述保护和 CLI 用户更新逻辑继续复用。

审计确认：外部终端直接启动 `docker exec` 不存在宿主输入分流层。Windows Terminal 默认会在终端消费 Ctrl+V；子 ConPTY 或 Docker stdin 代理无法把一个从未收到的按键还原为图片粘贴。PowerShell 本身不是终端宿主，不能依赖 PSReadLine 在原生 TUI 运行时接管按键。终端 settings 的 sendInput 可以配置专用动作，但不适合作为不修改全局设置的通用默认方案。

因此增加**可选择的自有终端显示层**，不再声称不透明的第三方终端具备图片 Ctrl+V。auto 模式为 AI CLI 选择该显示层，显式外部设置保留，当前外部窗口不做热接管。

## 新增数据链路

```text
当前智能终端内的 Qt Ctrl+V 事件
  → WindowsClipboard（序列号绑定的一次性快照）
  ├─ Text → bracketed paste → 原始 Docker 管道 → 容器内 Linux PTY → 同一 CLI
  └─ CF_HDROP / PNG / DIBV5 / DIB
       → 文件句柄 / PNG 编码 → 同一输入队列
       → Transfer.verify（复用 attach 审计）
       → docker exec -i 固定 Python 导入器（stdin 流，不启动 AI）
       → 既有项目 bind / 只读项目容器私有 tmp
       → SHA256、作用域、会话二次核验
       → Claude / Codex InputAdapter
       → 独立 bracketed paste 事件 → 原生图片标记确认
```

键盘与粘贴排在同一有界队列，不重启工具，不发送 Enter，不改写 CLI 的编辑缓冲区。Qt 主线程只处理界面/IME/VT；剪贴板争用重试、PNG 编码、文件流和 Docker 操作在工作线程。输出管道在独立线程排空，输出队列有界。0.14.3 的键盘和 resize 由同一私有管道传递给容器内 PTY，不定位外部窗口、不调用 SendInput、不安装钩子。本机预览仍使用 ConPTY。

`TerminalScreen` 使用 pyte 解析 VT、颜色、光标、历史，补充备用屏幕；`TerminalView` 提供 IME、键盘、选择复制和 CLI 请求的 SGR 鼠标报告。它不是新聊天 UI：CLI 完整 TUI 原样绘制，原生协议决定是否发送和读取附件。OSC52 不会读取或改写系统剪贴板。

## 文件级职责、风险与验证

| 文件 | 职责 | 主要风险/依赖 |
| --- | --- | --- |
| `clipboard.py` | Win32 格式识别、受限句柄拷贝、DIB/PNG | 位图畸形、剪贴板竞争；Win32 + 现有 Qt |
| `clipboard_file_windows.py` | 本机盘根句柄、NtCreateFile OBJ_DONT_REPARSE | 同时阻断中间重解析点，避免先检查再打开的竞争 |
| `clipboard_transfer.py` | 原件流、映射、版本适配、会话复核 | 容器切换、半批导入、CLI 版本变化 |
| `resources/checks/clipboard_transfer.py` | 无特权 stdin 导入、目录 FD、原子提交、配额/清理 | 链接穿越、并发；Linux 原语及既有可写目录 |
| `clipboard_cache.py` | 当前终端 OS 锁、作用域与七天保留 | 只清理已关闭会话，不存内容 |
| `terminal_pty.py` | 智能终端原始管道；本机 ConPTY / POSIX 生命周期 | 分帧、EOF/关闭/resize，Windows 10 兼容 |
| `resources/checks/terminal_relay.py` | 同一容器中 rootless Linux PTY | 帧长度/缓冲受限，断开时只挂断本次 PTY |
| `smart_terminal.py` | Qt 原地输入、VT 绘制、队列、图片确认 | TUI/键盘兼容及渲染成本，是复杂度最高的新增模块 |
| `terminal.py` / `engine.py` / `__main__.py` | 选择受控显示层并接入现有 attach | 显式外部设置不回退，公共 argv 不含 token |
| `ui/window.py` | 选项和兼容边界 | 不暗示第三方终端已经支持 |

宿主只打开用户主动复制的文件。导入器不接受源宿主路径，不调用 shell，所有目标组件由随机 hex 标识构成，目录打开使用 `O_NOFOLLOW`，目标文件排他创建、流式 SHA256、fsync 和原子提交。整个批次失败会移除本批已经提交的文件。容器账号保持原 UID、capabilities、seccomp 和网络保护，不新增端口、挂载、Docker socket、特权或环境凭据。

导入器通过 `python3 -I` 运行，避免加载项目内同名 `json.py`/`hashlib.py` 或用户 site；宿主源码模式的 attach 固定可信包目录并启用 Python safe path，避免在所选项目 cwd 导入宿主代码。这些规则不修改正常 AI 工具自己的项目加载行为。

项目 bind 在 Windows Desktop 中可能显示合成 UID；写入依赖已审计的挂载授权和目录句柄，不通过 root/chmod 改写项目所有权。私有 `/tmp` 仍验证目录所有者。Windows 缓存活动锁放在 JSON 文件 EOF 之外，不增长文件，避免阻止现有应用数据迁移读取元数据；终端连接结束会取消传输并释放锁，关闭时仍排空 ConPTY 输出以免阻塞。

文本屏蔽可退出 bracketed paste 的控制字符，保留换行、制表和 Unicode。无 bracketed paste 时拒绝自动粘贴，避免多行意外执行。图片必须是受支持的真实图片、模型支持视觉，并逐张观察到当前会话新增 `[Image #N]`。0.14.1 移除精确版本白名单和每次导入的独立版本查询；复制成功、会话标记和真实 CLI 视觉编码测试分别记录，未把未来版本全部列为通过。失败时按原子入队序号取消此前所有已排队的 Enter，新输入仍按序保留；不依赖Windows时钟精度。

图片文件先核验 PNG/JPEG/WebP 魔数与扩展名，再指定对应 Qt 解码器；不自动探测 SVG/TIFF 等其它插件，避免伪装成 PNG 的文件在宿主触发不必要的格式/外部资源处理。

## 依赖与回滚

新增 pyte 0.8.2（wheel 约 31 kB、LGPL-3.0）和 wcwidth 0.2.14（wheel 约 37 kB、MIT）。均为固定版本的纯 Python 包，无常驻服务、网络请求或容器镜像依赖。复用 PySide6 Essentials，不引入 QtWebEngine、浏览器终端或网页监听端口。

pyte 保持未修改；替换路径、源码取得方式和许可证见[第三方声明](../THIRD_PARTY_NOTICES.md)。Windows 打包把 pyte 源码放在 PYZ 外，以便替换。项目 PolyForm Noncommercial 许可不变。

设置仅新增 `terminal.kind=smart`，现有代理、Profile、项目数据格式不改。回滚先选择 Windows Terminal / PowerShell / 自定义终端并保存，再使用旧版；旧版不认识 smart 时需在新版中先切换。图片缓存不属于账号或项目源代码，不会自动删除用户数据，不重建镜像/容器。`auto` 的存储格式仍可被旧版读取。

## 依据

- [Microsoft：终端 paste 优先和 unbound](https://learn.microsoft.com/en-us/windows/terminal/customize-settings/actions#unbind-keys-disable-keybindings)
- [Microsoft：ConPTY 管道与独立线程](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session)
- [Microsoft：剪贴板格式](https://learn.microsoft.com/en-us/windows/win32/dataxchg/standard-clipboard-formats)
- [Microsoft：不跟随路径重解析点](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes)
- [Windows Terminal：ConPTY 启动与空标准句柄](https://github.com/microsoft/terminal/blob/main/src/cascadia/TerminalConnection/ConptyConnection.cpp)
- [Claude：图片粘贴和原生标记](https://code.claude.com/docs/en/interactive-mode)
- [Codex 0.167.0：图片路径 Paste 分类](https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/tui/src/bottom_pane/chat_composer/paste_input.rs)
- [Codex 0.167.0：视觉输入序列化](https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/tui/src/chatwidget/image_submission.rs)

## 0.14.1 终端交互与颜色修复

右键菜单提供复制/粘贴/全选/取消选择；选择快照涵盖已有滚动历史，输出继续接收但不会替换正在复制的内容。无选择的 Ctrl+C 与普通 Ctrl+A 仍交给 CLI。鼠标报告和强制选择模式分别处理。标题栏复用本项目 Qt TitleBar 和原生 startSystemMove/startSystemResize，不安装窗口消息钩子；移除顶部复制按钮，保留现有配色。

`terminal_render.py` 在未修改的 pyte 外补充有界 OSC10/11/4 颜色查询和冒号 SGR；Screen 保留淡色状态，绘制时缓存混色并显示加粗/下划线/删除线。仅自有终端的受审计 exec 增加公开 TERM/COLORTERM/TERM_PROGRAM，不改容器镜像、网络、权限或外部终端设置。颜色/光标协议回复使用有界优先队列，在等待图片确认时仍可响应，避免与原生附件输入相互等待。OSC52 不会读写 Windows 剪贴板。

参考 [Pebrel](https://github.com/Kuddev/pebrel) 的选择、右键菜单和终端显示功能；其 GPL-3.0 代码/字体/渲染器未并入本项目，现有许可和依赖保持不变。

## 0.14.2 鼠标分流

在自有窗口中延迟判定左键手势：单击把真实网格坐标编码为已协商的SGR Mouse按下/释放；移动超过拖选阈值后只选择终端快照，不向CLI发送拖动，松开时复制。普通点击不改系统剪贴板；不通过方向键、外部窗口标题、全局注入或读写CLI缓冲区定位。右键的主动粘贴复用同一剪贴板/输入队列，抑制该次原生菜单事件避免双重操作；Shift右键及键盘菜单保留。原生鼠标没有启用时不猜测编辑位置。

Qt原生CLI夹具增加多行、中文、指定位置编辑、右键文字/图片粘贴，并在合成API核对实际文本片段和图像。产品不解析屏幕文字来寻找输入区；测试夹具按唯一合成文本定位点击目标，仅用于验证。

## 0.14.3 Windows 10 路径与输入法

Windows 10 内置 ConPTY 会丢弃鼠标跟踪开关，Windows Server 新版的成功不能覆盖这一系统差异。依据：[Microsoft 原始修复](https://github.com/microsoft/terminal/pull/4856)、[Bun 的 Windows 10 / Server 2019 实测与系统版本说明](https://github.com/oven-sh/bun/commit/c508647f35d052d2ef073359e2e2e02f92a99508)。本次 Windows 新版探针也观察到完整透传，但不把它记为 Win10 已复现。

智能终端改用不带本机控制台的 `docker exec -i`，在已审计的同一个项目容器、同一 UID 和访问范围下用 Python 标准库建立 Linux PTY。可信包脚本通过 `python3 -I -c` 运行，不从项目导入模块。宿主 stdin 为 D（输入）/R（网格）/C（关闭）长度帧，单帧不超过64KiB，stdout 原样保留 VT。远端使用有界非阻塞缓冲、PTY 窗口大小和同一终端前台作业的挂断；关闭只结束自己创建的 exec 客户端和 PTY，不关闭 Docker 或其它会话。无需重建镜像、新挂载、端口或权限。每个打开的终端增加一个容器内 Python 中继进程，退出时回收。

`QTextLayout` 仅在 Qt 本地显示 IME 预编辑：按终端基线排列、覆盖提示文本、处理原生格式与 UTF-16 游标，候选位置随组合文字变化。确认前不会写入 PTY；取消只移除覆盖层，不改 CLI 缓冲。普通滚轮清理已复制的选择快照，交还原生对话滚动；Shift+滚轮继续查看终端缓存。剪贴板 CRLF/CR 仅在 bracketed paste 体内变成 LF，右键不会生成 Enter。


## 0.14.4 绘制、编辑、偏好与时区

当前交互以本节为准：Codex已协商鼠标后立即转发按下、拖动和释放；宿主另保留复制快照。字符半格及宽字符边界决定插入点。Ctrl+A仅在就绪Codex中选择草稿，Delete在确认存在草稿后请求CLI原生清空；历史选择不进入编辑删除。右键只粘贴，所有菜单移至右上角，取代旧版Shift右键菜单。

`terminal_paint.py`使用有界QStaticText/行LRU缓存；`smart_terminal.py`分批解析输出、合并脏区域更新，保留输入顺序和最终EOF。`terminal_preferences.py`提供独立schema1、原子写入、跨进程字段合并及关闭提交；`window_effects.py`仅操作自有HWND、遵守系统透明/高对比度开关，失败回退纯色。首次启用透明窗口须下次打开生效。

`workspace_timezone.py`在项目原可写层部署固定公开时区文件，浏览器通过无网络/无用户挂载的离线准备容器生成公共配置镜像并恢复原UID/入口/命令。浏览器运行保持只读和原沙箱；不提交用户层，不修改Etc/UTC数据库。旧控制容器文件独立诊断。

文件、风险、实测数据、回滚和实体Windows待验范围见[终端外观与性能](terminal-appearance-performance.zh-CN.md)。参考[Qt QStaticText](https://doc.qt.io/qt-6/qstatictext.html)、[Qt透明属性约束](https://doc.qt.io/qt-6/qt.html#WidgetAttribute-enum)、[Microsoft系统背景](https://learn.microsoft.com/en-us/windows/apps/develop/ui/system-backdrops)及[Codex原生草稿清空](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/tui/src/bottom_pane/chat_composer.rs)。无新依赖，许可不变。
