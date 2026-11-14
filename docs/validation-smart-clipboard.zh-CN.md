# Smart Clipboard 验证记录

## 0.14.5补充

针对Acrylic标题栏穿透、移动／缩放及滚动闪烁，增加真实Windows窗口像素与WindowFromPoint检查、原生／兼容材质切换、最大化和150%DPI。CI兼容接口测试不等于Windows10实体拖动或DWM观感验收。滚动测试将子视口明确设为1920×1080，逐个检查同步清屏分包期间的画面和完成后像素；旧版在三个检查点出现半帧，新实现要求为零。

本地Linux ARM64全套556项测试通过（29项按平台跳过）；500组混合VT字符／颜色／换行／插入／字符集／组合字符对原pyte逐格一致。真实Claude2.1.319与Codex0.169.0的Qt输入、原生图片序列化、草稿删除及120行历史回归通过。实机视觉和模型理解仍不记为已验收。结果及复现脚本见[终端外观与性能](terminal-appearance-performance.zh-CN.md)，最终发布流水线核对冻结包和保护工作区回归。

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

## 0.14.3 Windows 系统差异与长对话回归

- [Windows 专项](https://github.com/engeeeee/ENGE-SPX/actions/runs/43565174057)通过真实 Win32 ConPTY 探针、原始管道、Qt IME 和原鼠标操作测试。该 runner 是较新的 Windows Server，不充当物理 Windows 10；原生鼠标在 Win10 内置 ConPTY 丢失的限制由上游实测佐证。本版智能终端已经绕过该路径。
- `tests/test_terminal_relay.py` 验证真实宿主 PIPE、鼠标/Unicode/bracketed paste 字节、网格更新、EOF、阻塞写入回收；有 Docker CLI 的 Windows/Linux 还通过一次性回环假 Engine 检查真实 docker 客户端 hijack，不需要 daemon。只有测试夹具使用回环监听，产品没有新增端口。
- `tests/test_terminal_usability.py` 通过原生 Qt IME preedit/commit/cancel 事件和像素对比检查背景遮盖、字体基线、换行、UTF-16 候选光标；复制快照不能截断后续原生滚动，滚轮小增量会累积。
- Linux ARM64 的真实 Codex **0.169.0**、镜像 Codex **0.167.0** / Claude **2.1.319** 通过同一 Qt 窗口及实际 Linux PTY relay。检查预编辑不发送、确认一次、原生两图、草稿/进程不变；Codex 另验证右键末尾 CRLF/CR 不发送、120行完整对话、复制后向上滚到第0行、回到底部后草稿仍存在。API夹具会记录所有真实生成请求，文本请求也参与提前提交检查。
- Docker 集成额外在现有受保护项目容器通过实际 `Engine.attach_command` 启动 relay，核对 UID1000、真实终端、resize、鼠标/多行粘贴字节及同容器复用。完整 Windows 打包及 Docker 结果以0.14.3发布流水线为准。
- 时区以真实 TZif 分别核对进程与系统文件，LA/UTC不一致和相同文件均有测试；只读报告，不改设置、文件或容器权限。**系统时区统一仍未实现。**

物理 Windows 10 + Docker Desktop、具体输入法候选窗与真实模型理解仍未人工验收。没有实机修改前后 CPU/内存比较；每个打开的智能终端多一个 Python 标准库 PTY relay，缓冲有界，不为每次粘贴创建进程或 AI 会话。


## 0.14.4 外观、选择删除与性能

本地Linux ARM64全部550项单元测试完成（521通过，29按平台跳过）。真实Codex0.169.0、镜像内0.167.0和Claude2.1.319的Qt路径回归通过；Codex覆盖Ctrl+A/Delete、空草稿重复删除、拖选部分删除、连续混合粘贴和回答期间清空草稿。合成API检查删除不新增请求、不截断返回流；仍未使用真实账号/模型。

[独立Windows与Docker探针](https://github.com/engeeeee/ENGE-SPX/actions/runs/43575988169)两项通过：同机渲染前后对比、旧项目可写层/容器ID保留、只读非root浏览器时区一致、UTC数据库未改写、缓存镜像复用、无新端口/挂载。最终Windows单元、冻结包和完整网络沙箱回归由该版本发布流水线记录。

新增偏好跨进程合并、损坏配置保留、权限失败、关闭提交、重开真实产品窗口恢复、透明背景不累积、行缓存界限、大量输出/EOF让出键盘处理测试；Windows平台还调用自有窗口的真实背景API，但接受接口返回不等于物理桌面观感验收。

性能数值、复现命令、Acrylic系统兼容及Codex默认编辑模式限制见[终端外观与性能](terminal-appearance-performance.zh-CN.md)。实体Windows10/11、多DPI显示器切换、高刷新率手感、Vim/自定义键位和真实模型验收仍需人工记录，不能用本次合成测试替代。
