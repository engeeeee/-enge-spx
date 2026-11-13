# Smart Clipboard 架构与审计

## 现有调用关系与选择

```text
GUI Controller.open_tool
  → Engine.terminal → _tool_session / ready / _project
  → 外部终端或自有终端进程的公共 spx attach 参数
  → Engine.attach_command（guard、session、container、Profile、挂载审计）
  → docker exec -it → tool_session.command → 原有 Claude / Codex TUI
```

原有 `terminal.py` 使用 argv 启动 Windows Terminal、无 Profile 的 PowerShell 或自定义 exe。项目目录 bind 位于 `/workspace/<key>`，账号 home 按 Profile 使用既有卷，项目容器与浏览器分开，`attach` 拒绝过期会话。上述保护和 CLI 用户更新逻辑继续复用。

审计确认：外部终端直接启动 `docker exec` 不存在宿主输入分流层。Windows Terminal 默认会在终端消费 Ctrl+V；子 ConPTY 或 Docker stdin 代理无法把一个从未收到的按键还原为图片粘贴。PowerShell 本身不是终端宿主，不能依赖 PSReadLine 在原生 TUI 运行时接管按键。终端 settings 的 sendInput 可以配置专用动作，但不适合作为不修改全局设置的通用默认方案。

因此增加**可选择的自有终端显示层**，不再声称不透明的第三方终端具备图片 Ctrl+V。auto 模式为 AI CLI 选择该显示层，显式外部设置保留，当前外部窗口不做热接管。

## 新增数据链路

```text
当前智能终端内的 Qt Ctrl+V 事件
  → WindowsClipboard（序列号绑定的一次性快照）
  ├─ Text → bracketed paste → 当前 ConPTY → 同一 CLI
  └─ CF_HDROP / PNG / DIBV5 / DIB
       → 文件句柄 / PNG 编码 → 同一输入队列
       → Transfer.verify（复用 attach 审计）
       → docker exec -i 固定 Python 导入器（stdin 流，不启动 AI）
       → 既有项目 bind / 只读项目容器私有 tmp
       → SHA256、作用域、会话二次核验
       → Claude / Codex InputAdapter
       → 独立 bracketed paste 事件 → 原生图片标记确认
```

键盘与粘贴排在同一队列，不重启工具，不发送 Enter，不改写 CLI 的编辑缓冲区。Qt 主线程只处理界面/IME/VT；剪贴板争用重试、PNG 编码、文件流和 Docker 操作在工作线程。输出管道在独立线程排空，输出队列有界。ConPTY resize 和终端报告复用本终端的句柄，不定位外部窗口、不调用 SendInput、不安装钩子。

`TerminalScreen` 使用 pyte 解析 VT、颜色、光标、历史，补充备用屏幕；`TerminalView` 提供 IME、键盘、选择复制和 CLI 请求的 SGR 鼠标报告。它不是新聊天 UI：CLI 完整 TUI 原样绘制，原生协议决定是否发送和读取附件。OSC52 不会读取或改写系统剪贴板。

## 文件级职责、风险与验证

| 文件 | 职责 | 主要风险/依赖 |
| --- | --- | --- |
| `clipboard.py` | Win32 格式识别、受限句柄拷贝、DIB/PNG | 位图畸形、剪贴板竞争；Win32 + 现有 Qt |
| `clipboard_file_windows.py` | 本机盘根句柄、NtCreateFile OBJ_DONT_REPARSE | 同时阻断中间重解析点，避免先检查再打开的竞争 |
| `clipboard_transfer.py` | 原件流、映射、版本适配、会话复核 | 容器切换、半批导入、CLI 版本变化 |
| `resources/checks/clipboard_transfer.py` | 无特权 stdin 导入、目录 FD、原子提交、配额/清理 | 链接穿越、并发；Linux 原语及既有可写目录 |
| `clipboard_cache.py` | 当前终端 OS 锁、作用域与七天保留 | 只清理已关闭会话，不存内容 |
| `terminal_pty.py` | 自有 ConPTY 进程和管道生命周期 | Win32 ABI、EOF/关闭/resize；POSIX 后端用于测试 |
| `smart_terminal.py` | Qt 原地输入、VT 绘制、队列、图片确认 | TUI/键盘兼容及渲染成本，是复杂度最高的新增模块 |
| `terminal.py` / `engine.py` / `__main__.py` | 选择受控显示层并接入现有 attach | 显式外部设置不回退，公共 argv 不含 token |
| `ui/window.py` | 选项和兼容边界 | 不暗示第三方终端已经支持 |

宿主只打开用户主动复制的文件。导入器不接受源宿主路径，不调用 shell，所有目标组件由随机 hex 标识构成，目录打开使用 `O_NOFOLLOW`，目标文件排他创建、流式 SHA256、fsync 和原子提交。整个批次失败会移除本批已经提交的文件。容器账号保持原 UID、capabilities、seccomp 和网络保护，不新增端口、挂载、Docker socket、特权或环境凭据。

导入器通过 `python3 -I` 运行，避免加载项目内同名 `json.py`/`hashlib.py` 或用户 site；宿主源码模式的 attach 固定可信包目录并启用 Python safe path，避免在所选项目 cwd 导入宿主代码。这些规则不修改正常 AI 工具自己的项目加载行为。

项目 bind 在 Windows Desktop 中可能显示合成 UID；写入依赖已审计的挂载授权和目录句柄，不通过 root/chmod 改写项目所有权。私有 `/tmp` 仍验证目录所有者。Windows 缓存活动锁放在 JSON 文件 EOF 之外，不增长文件，避免阻止现有应用数据迁移读取元数据；终端连接结束会取消传输并释放锁，关闭时仍排空 ConPTY 输出以免阻塞。

文本屏蔽可退出 bracketed paste 的控制字符，保留换行、制表和 Unicode。无 bracketed paste 时拒绝自动粘贴，避免多行意外执行。图片必须是受支持的真实图片，CLI 版本已验证、模型支持视觉，并观察到新增 `[Image #N]`；复制成功与原生视觉编码测试分别记录。

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
