# Smart Clipboard 验证记录

开发日期：2026-11-13。开发分支 `feature/smart-clipboard`；不是已发布版本的验收声明。

## 已运行

- Linux ARM64、Python 3.14.4、PySide6 6.12.0：新增剪贴板格式转换、Unicode/多行、控制字符边界、流式导入、校验失败回滚、链接阻断、只读 tmp、配额、会话锁、输入顺序、版本限制及原生图片标记确认测试。
- 原有 436 项测试在接入受控终端后通过，19 项平台测试在 Linux 跳过；新增测试后的完整结果在最终验证时补充。
- 官方原生 Linux ARM64 Claude Code **2.1.319** 与 Codex **0.167.0**，独立测试 HOME、合成图片、真实 PTY/TUI：同一草稿中保留前后中文，分别出现两个原生 `[Image #N]`，不发送 Enter，不重启 CLI。Codex 使用 `--no-daemon` 研究夹具消除包外 server 依赖；产品不添加该参数。
- 这一步证明真实 TUI 的附件转换，**不等于真实模型已经识图**。API 请求中的图片内容、真实 Windows ConPTY/剪贴板及人工测试需分项记录，不能由单元测试推导为通过。

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python tools/check_repository.py
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python tools/smoke_gui.py
```

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

真实测量应记录同一项目/图片、同一 Docker/WSL2/CLI 版本，分别比较外部终端与智能终端的空闲占用、截图到标记耗时、10/128 MiB 文件导入、连续输入期间的响应及全部关闭后的回收。使用现有 Resources 记录机制区分主 GUI、终端进程、容器和 WSL2；缺少测量保持“未测”，不能写为零。
