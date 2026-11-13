# Smart Clipboard 验证记录

开发日期：2026-11-13；随 0.14.0 发布。自动化验证与真实 Windows / 模型人工验收分别记录，发布不表示后者已完成。

## 已运行

- Linux ARM64、Python 3.14.4、PySide6 6.12.0：新增剪贴板格式转换、Unicode/多行、控制字符边界、流式导入、校验失败回滚、链接阻断、只读 tmp、配额、会话锁、输入顺序、原生图片标记确认测试。
- 功能提交 `41d9035` 的最终 [CI](https://github.com/engeeeee/ENGE-SPX/actions/runs/43424348817) 全部通过：Windows Python 3.12 共489项，472通过、17跳过；Linux Python 3.12 共489项，462通过、27跳过。本机 Linux ARM64 Python 3.14 同样通过，GUI、多档 DPI、冻结打包和安装卸载通过。
- 真实 Windows API 验证 CF_UNICODETEXT、CF_HDROP、CF_DIB、CF_DIBV5、PNG、4K 像素、Unicode/emoji/多行、ConPTY bracketed paste、剪贴板占用/变化、中间 junction 阻断；Qt 当前窗口 Ctrl+V、复制/中断、Tab、停止及快照释放通过。物理桌面操作仍另列人工验收。
- 官方 Claude Code **2.1.319** 与 Codex **0.167.0**，隔离 HOME、真实 PTY/TUI 和合成 API：同一草稿保留前后中文及两张原生 `[Image #N]`；粘贴期间不提交，明确 Enter 后分别发送两个 `image` / `input_image`，解码尺寸160×100和两种像素颜色一致。测试不使用真实账号、模型或系统剪贴板；不把图片请求序列化当作模型理解。
- 真实 Docker 导入4个文件（含2,400,000字节分块流），SHA256一致、UID1000、复用容器与原挂载、拒绝过期 session；只读项目私有 tmp 与跨身份不可见检查通过。现有协议链、沙箱、190秒续期、数据/Profile迁移、退出与资源回归通过。
- 资源基准首轮因外部代理传输失败中断；仅重跑失败的 containers job 后通过，未修改源码或放宽保护。[最终证据附件](https://github.com/engeeeee/ENGE-SPX/actions/runs/43424348817/artifacts/14038109390)包含运行时、图像合成 API、Profile、网络与资源记录。0.14.0 发布元数据和同版本产物另由本次 main 流水线检查，见 [Actions](https://github.com/engeeeee/ENGE-SPX/actions/workflows/ci.yml)。
- **真实模型是否理解图片仍未验收**。合成 API 证明的是 CLI 已编码视觉输入，不能把接收夹具当作模型识图结果。真实 Windows + Docker Desktop + 已登录账号的操作仍需下表人工验收。

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python tools/check_repository.py
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python tools/smoke_gui.py

# 已安装的官方原生 Linux 可执行文件；只用隔离测试 HOME 与本地合成 API
PYTHONPATH=src python tests/integration_cli_clipboard.py \
  --claude /absolute/path/to/claude \
  --codex /absolute/path/to/complete-codex-package/bin/codex \
  --qt-terminal --capture-terminal /tmp/clipboard-terminal.png \
  --output /tmp/clipboard-native-api.json
```

`tests/clipboard_runtime_checks.py` 已接入原有 Docker 集成：在完整保护的工作区中验证真实图片/文本/代码/大块流的 SHA256、UID1000、容器复用与过期 session 拒绝；身份/只读集成验证私有 tmp 和跨容器不可见。原生 API 夹具只从测试镜像提取系统安装的程序，不复制账号卷；结果作为 CI 测量附件保存。

`tests/test_windows_clipboard.py` 在 Windows 原生读取真实 CF_UNICODETEXT、CF_HDROP、CF_DIB、CF_DIBV5 和 PNG，并测试剪贴板变化及真实 ConPTY。它会替换/清空测试桌面的剪贴板，不读取或备份个人剪贴板。使用一次性测试桌面；非 Windows 明确 skip。

## 必须人工验收、不能冒充已通过

使用[Windows 验收脚本](../tools/Test-SmartClipboard.ps1)生成只含合成数据的夹具并核对环境。保持真实用户账号资料不变，选择测试项目/身份。

| 场景 | 操作与证据 | 当前状态 |
| --- | --- | --- |
| 截图视觉 | Win+Shift+S 截图包含随机文字/图形；同一 Claude/Codex 草稿 Ctrl+V；原生标记；手动 Enter；模型准确描述 | 待真实 Windows + 模型验收 |
| 多图片/混合 | 输入前缀、粘贴两图、输入后缀、粘贴日志；先不发送，核对顺序与未丢草稿 | 原生 Linux TUI 图片/文字部分已观察；完整 Windows 待验 |
| PDF/代码 | Explorer 复制夹具，Ctrl+V；引用路径可读；要求 CLI 读取指定随机内容，PDF 解析依赖实际工具 | 待真实 Windows + 工具验收 |
| 原生键盘 | Unicode/IME、多行文字、Ctrl+C、Ctrl+Shift+C、历史/Tab/Shift+Enter、选择/鼠标 | 自动化基础测试；真实桌面待验 |
| 双项目/只读 | 同时开启两个项目；粘贴结果只进入对应输入；只读宿主无新增文件，另一项目无新增挂载 | 自动化隔离测试；Desktop/WSL2 待验 |
| 容器重启 | 导入时停止环境，旧窗口不能继续复制到替换 session；新窗口正常，原输入不自动发送 | 自动化绑定检查；真实 Desktop 待验 |
| 失败/大文件 | 占用文件、畸形图片、空剪贴板、超过上限、磁盘写失败；草稿保留且队列回车取消 | 自动化测试；真实桌面待验 |
| 外部终端 | 显式选择 Windows Terminal、PowerShell、自定义；正常启动与普通文本粘贴；不会宣称图片无感支持 | argv 回归通过；桌面待验 |

## 性能状态

目前没有真实 Windows 上修改前/后的 CPU、内存或粘贴延迟对比，不提供提升百分比。新增终端使用现有 Qt DLL 和两个小型纯 Python 包，不新增常驻剪贴板服务、宿主监听端口或浏览器引擎。文件 1 MiB 分块复制，单个受控导入最长 120 秒，操作不占 GUI 主线程；每次粘贴使用当前容器和 AI 会话。

已测单项成本：上述 Windows CI 把 **3840×2160 CF_DIBV5** 读取并编码为 PNG，用时 **426.56 ms**，输出 **37561 字节**，像素与原始分辨率一致。这是合成纯色 4K 图片的一次剪贴板转换，**不包括 Docker、CLI 和模型耗时**，不能代表所有截图或机器。输出不含原始图片/剪贴板内容。终端停止后拒绝继续读取系统剪贴板；已处理快照会释放，活动缓存锁不妨碍应用数据复制迁移。

真实测量应记录同一项目/图片、同一 Docker/WSL2/CLI 版本，分别比较外部终端与智能终端的空闲占用、截图到标记耗时、10/128 MiB 文件导入、连续输入期间的响应及全部关闭后的回收。使用现有 Resources 记录机制区分主 GUI、终端进程、容器和 WSL2；缺少测量保持“未测”，不能写为零。

## 0.14.1 回归

修复0.14.0对用户已更新工具的精确版本拦截。新增实际产品 Qt 窗口 Ctrl+V → 同一真实 CLI → 两张原生附件 → 明确 Enter → 合成 API 图像块检查，版本从实际可执行程序读取，不再写死测试版本。Linux ARM64 的 Codex 0.169.0 已验证；镜像版本 Codex 0.167.0 / Claude 2.1.319 也经过同样 Qt 路径回归。合成 API 仍不等于真实模型理解；宿主剪贴板和 Docker 文件导入分别由现有 Windows/API 与 Docker 集成核验。

新增测试覆盖：右键不自动读取剪贴板、实际菜单、Unicode拖选/双击、历史全选、选择期间持续输出、鼠标报告下Shift拖选、Ctrl+C/Ctrl+A保持、字号调整、自定义边框/按钮移除、ANSI/256/RGB/淡色/粗体等、颜色查询跨块/超长边界、OSC52隔离、图片等待期间协议回复、失败前多个排队回车全部取消，以及真实自有 PTY 的颜色输出。Windows 与冻结包实际结果以0.14.1的发布CI为准；缺少的物理Windows/模型组合仍列为待验。

## 0.14.2 鼠标行为回归

用户明确选择默认“左键拖选自动复制到剪贴板、右键输入区粘贴”。新增单击与拖选分流、无选择不覆盖剪贴板、原生鼠标开启时仍能自动复制、右键只粘贴一次、不打开菜单或自动发送、Shift右键/键盘菜单和自动复制开关检查。

真实Codex 0.169.0在同一Qt窗口中点击两行不同位置、插入中文和标记，右键粘贴文字与图片，保留草稿及两张图片，在明确Enter后核对合成API实际文本和图像。Codex的鼠标能力来自原生SGR协商，未模拟方向键。Windows源码、冻结包和Docker结果以0.14.2发布CI为准；真实用户模型与物理设备验收仍另列。
