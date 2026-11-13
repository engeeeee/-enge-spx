# 0.13.5 退出预算与工具更新验证

## 已取得的证据

反馈 JSON 明确运行 Windows x64 / 0.13.4 / desktop-linux，管理状态不可用，离线核验在 preflight 的 `unsupported_or_expired` 被拒绝，未执行进程/管道/WSL 检查。由于该版本在真实 Windows 上使用 os.name=nt，这指向离线核验预算已耗尽；报告本身不能单独证明哪一个子进程拖延。CPython 3.12 的 Windows subprocess.run 实现会在捕获 PIPE 的子进程超时后 kill 该进程，再无超时调用 communicate；Docker CLI 插件继承句柄时可能拖延这一步。

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

Windows/CI 容器最终结果与发布附件在实际执行完成后记录，未运行不计通过。本机未运行 Docker 集成，交由现有真实 Linux x64 Docker CI 门禁执行。真实 npm 安装检查使用镜像固定包版本，验证从系统安装切换到用户安装与再次启动，不能冒充真实账号的交互更新或未来所有第三方版本的兼容验收。

## 性能与限制

无额外常驻监测、监听或全局虚拟机操作。管理捕获只在退出期间使用临时文件；输出不写入诊断报告，超时不等待插件的输出句柄。GUI 工具结束后仅用户已打开的会话保留一个容器 Shell，停止环境仍按原规则结束它；非交互启动增加一次短暂 Shell 包装。用户下载的 CLI 版本占用当前身份持久卷，未复制整份镜像的系统工具，不宣称降低下载体积或 CPU/内存百分比。

反馈设备后续进程、配置和 WSL 证据仍需运行修复版后确认；本批没有用跳过核验来解决未知状态。Windows 原生测试只使用测试自有进程/句柄，不操作真实 Desktop，Docker 验证使用 Linux CI 和合成身份，不使用真实 AI 账号。
