# 0.13.5 退出预算与工具更新验证

## 已取得的证据

反馈 JSON 明确运行 Windows x64 / 0.13.4 / desktop-linux，管理状态不可用，离线核验在 preflight 的 `unsupported_or_expired` 被拒绝，未执行进程/管道/WSL 检查。由于该版本在真实 Windows 上使用 os.name=nt，这指向离线核验预算已耗尽；报告本身不能单独证明哪一个子进程拖延。[CPython 3.12 的 Windows subprocess.run 实现](https://github.com/python/cpython/blob/3.12/Lib/subprocess.py)会在捕获 PIPE 的子进程超时后 kill 该进程，再无超时调用 communicate；Docker CLI 插件继承句柄时可能拖延这一步。

工具镜像中 Codex / Claude 以 root 安装在系统 npm 前缀，实际项目 UID 为 1000；原 attach 直接运行工具，工具为更新退出后会结束终端会话。该权限与会话问题均在源码中确认，与特定 Windows 终端品牌无关。

## 实施文件与兼容性

- `local_process.py`：私有临时文件替代管理输出 PIPE，限量读取，保留返回码；超时只回收本次命令行进程，不等待插件 EOF、不杀 Desktop / WSL。
- `desktop_shutdown.py` / `desktop_offline.py`：工作区总预算 20 秒，保留最多 8 秒给完整独立证据；区分管理超时、预算耗尽和平台不适用。停止接受规则与联合关闭 60 秒时限保留。
- `tool_session.py` / `engine.py`：通过固定 Shell 脚本和独立 argv 为当前身份设置持久前缀及 PATH；非交互 exec 保留原退出码，GUI AI 工具结束后留在同一受控容器 Shell，不自动重跑。
- 扩展原 Desktop/退出测试，新建原生子进程句柄与 Linux Shell 测试；复用 Docker 集成，在实际网关路径安装镜像固定版本的两个官方 npm 包，验证用户目录解析、非 root 权限、环境恢复/迁移后的版本；身份集成覆盖用户更新标记的隔离与恢复。

没有更改配置格式、镜像配方、生产依赖、许可证、容器用户、capabilities、seccomp、项目挂载或网络例外。账号/代理/Profile 仍使用原格式与卷。用户工具目录第一次使用才创建；更新下载由用户或工具既有更新流程触发，不在启动时额外安装 latest。旧版本忽略用户安装目录，不需要逆迁移，但不具备本批路径优先级和停留行为。

## 测试命令与结果

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_desktop*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_local_process.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_tool_session.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/check_repository.py
node --test tests/test_release_publication.cjs
PYTHONPATH=src python tests/integration_runtime.py --context default --output integration.json
PYTHONPATH=src python tests/integration_profiles.py --context default --runtime-report integration.json --output profiles.json
```

本地 Linux ARM64 完整单元回归 424 项，408 通过、16 项平台专用跳过，约 16.0 秒；9 项发布助手测试、Qt GUI smoke、75 篇文档/版本和 diff 检查通过。真实自有子进程继承输出句柄的限时回收、管理阶段预留完整 8 秒、GUI 工具结束后留在 Shell 并解析用户版本、普通 CLI 退出码和特殊参数均通过。镜像三项配方与 0.13.4 完全一致。

[CI #43355239594](https://github.com/engeeeee/ENGE-SPX/actions/runs/43355239594) 使用源码 `ac60abb61b9f96a9dcc1c2f69f94a0dd52254cbf`。Windows 424 项中 417 通过、7 项平台专用跳过，约 125.2 秒；Linux 424 项中 408 通过、16 项跳过，约 17.9 秒。两个平台各 9 项发布助手检查通过，Qt GUI smoke、125% / 150% / 200% DPI 及 Windows 打包门禁通过。真实自有插件继承输出句柄的超时检查在 Windows 上通过。

真实 Linux x64 Docker 门禁已通过两个官方 npm 包的 UID 1000 用户目录安装、后续可执行文件解析和重启/数据迁移保留；系统安装目录保持不可写。独立身份更新标记、账号和浏览器 Cookie/Storage 隔离及异常停止通过。原有 DNS/UDP/IPv6、TLS/Reality/gRPC/QUIC、浏览器沙箱、中文 PTY 和 190 秒无 Shell 输入续期均通过。

首次容器任务在本批功能及身份验证通过后，旧版固定基线的 confirm 出口探测报 `SPX_PROBE:proxy_or_transport_failure`，日志不能区分具体上游或传输原因，因此未发布。仅重跑失败容器任务和依赖发布任务，复用通过的 Windows/打包产物；第二次同一源码的性能基线已通过，没有放宽探测或修改停止接受条件。运行环境归档在 containerd 和 classic 两种镜像存储下导入、实际启动检查均通过；最终发布任务成功。

本机未运行 Docker 集成，使用上述真实 Linux x64 Docker CI 证据。真实 npm 安装检查使用镜像固定的 Codex 0.167.0 / Claude 2.1.319，验证从系统安装切换到用户安装与再次启动，不能冒充真实账号的交互更新或未来所有第三方版本的兼容验收。

## 性能与限制

无额外常驻监测、监听或全局虚拟机操作。管理捕获只在退出期间使用临时文件；输出不写入诊断报告，超时不等待插件的输出句柄。GUI 工具结束后仅用户已打开的会话保留一个容器 Shell，停止环境仍按原规则结束它；非交互启动增加一次短暂 Shell 包装。用户下载的 CLI 版本占用当前身份持久卷，未复制整份镜像的系统工具，不宣称降低下载体积或 CPU/内存百分比。

反馈设备后续进程、配置和 WSL 证据仍需运行修复版后确认；本批没有用跳过核验来解决未知状态。Windows 原生测试只使用测试自有进程/句柄，不操作真实 Desktop，Docker 验证使用 Linux CI 和合成身份，不使用真实 AI 账号。

## 正式发布与公开下载复核

[0.13.5 正式版](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.5-windows) 为非草稿、非预发布的最新正式版，标签指向上述 `ac60abb` 源码。实际下载的 Windows 附件：

| 附件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| Setup | 34,389,858 | `c1359e3d7b964af7b6640c933ccdb5c22ee8704a76d956eba869b3f612e5c70e` |
| Portable | 52,960,511 | `bd1e0338aa878f2b7541ce475c8c34cf7df7c6c7e61ed8d256d5348c97b4d130` |
| Runtime linux-amd64 | 875,959,577 | `9b7bbb7fc2b6545c58551a550d94393234422024f74b6e7264a41c6f0456dd98` |

Setup/Portable 实际字节、公开校验文件和 GitHub digest 一致，ZIP CRC 正确。两个 EXE 的 File/ProductVersion 为 `0.13.5.0`，正式版本标记正确；冻结模块和实现标记确认包含 `local_process` 的 TemporaryFile 捕获、`tool_session` 的用户 npm 前缀、预留核验预算及已有复制诊断入口。运行环境不重复下载：公开清单、归档大小/digest 与本次成功 CI 的导出及两种镜像存储导入证据一致。0.13.4 的既有安装包和便携包校验值保持不变。

同次性能记录保留基线 normal、候选 normal/low 三组、每组从环境未启动到完全停止的七阶段数据。该基线为既有固定历史版本，属于 Linux 同主机合成负载，不是用户设备上 0.13.4→0.13.5 的性能对照；本次不据此声称加速比例或真实 AI 请求性能。
