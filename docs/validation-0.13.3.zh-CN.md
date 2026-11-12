# 0.13.3 Docker 后台已退出时的收尾修复

## 问题与范围

0.13.2 已处理管理接口明确返回 stopped 的手动退出顺序。实际反馈暴露另一条路径：连 Desktop 后台及管理接口也退出后，Linux 引擎管道和状态 API 一起消失，原逻辑无法获得 stopped，重新抛出缺失管道错误并保留界面。本批只补充这一离线证据路径，保留原退出机制及账号、代理、身份、预算、镜像和许可。

## 文件与方案

- `src/enge_spx/desktop_offline.py`：只读检查 WSL2 设置、严格进程快照、固定本机管道和 WSL 注册/运行列表，重复检查进程及管道；不输出原始命令结果或用户发行版名称。
- `desktop_shutdown.py`：管理状态不可用时，只允许精确本机 Desktop Linux context 使用独立证据；联合关闭的状态确认也使用此路径，沿用总时限。
- `process_metrics.py`：为停止证据增加严格枚举，失败/部分列表不能视为空；资源显示保留默认宽容模式。
- `tests/test_desktop_offline.py`、`test_desktop_shutdown.py`、`test_exit_lifecycle.py`：覆盖接口消失、权限/编码/超时、仍运行、重启、未知/不匹配上下文、凭据清理与数据保留；Windows 门禁实际调用 Win32 私有测试管道和进程快照。
- 版本、打包元数据、CI 资产与本次文档同步为 0.13.3。无配置格式或生产依赖变更；回滚无需逆迁移。

管理状态明确 running / starting / stopping / paused 时，不用离线证据覆盖它。单独管道缺失或仅无前台窗口始终不足。独立路径要求设置明确为 WSL2，不能用于 Hyper-V 或未知后端。其它运行中的 WSL 发行版不被停止。Engine 仍先撤销授权、等待本实例 guard/forward/relay，然后重新核验。

依据为 [Docker status JSON 接口](https://docs.docker.com/reference/cli/docker/desktop/status/)、[WSL 列表命令](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)、[Microsoft WSL 列表实现](https://github.com/microsoft/WSL/blob/master/src/windows/common/WslClient.cpp)、[Win32 管道等待](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-waitnamedpipew)及 [进程枚举结束状态](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-process32nextw)。源码不复制第三方实现。

## 本地验证

原版函数与候选函数在相同的“管理接口失败、独立证据满足”输入下，分别返回 False / True，复现并覆盖缺失分支。

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_desktop*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_exit*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/check_repository.py
node --test tests/test_release_publication.cjs
```

Linux ARM64 专项：Desktop 34 项（32 通过、2 项 Win32 专用跳过）；退出 34 项通过。完整本地回归 401 项：386 通过、15 项 Windows 专用跳过，用时约 11.6 秒；9 项发布助手测试、Qt smoke 和 70 篇文档/版本元数据检查通过。未执行/跳过不记为通过。

同次 [完整 CI](https://github.com/engeeeee/ENGE-SPX/actions/runs/43195721077) 的 Windows 回归 401 项：397 通过、4 跳过；Linux 401 项：386 通过、15 跳过。两平台各 9 项发布助手测试通过。Windows 实际创建/检查/关闭独立测试管道并执行严格进程快照；Qt smoke 与 125%/150%/200% 布局通过。冻结 Python 3.12.10 EXE、DPAPI 迁移和删除、手动启动、托盘、联合退出开/关、先关闭 Desktop 后退出及安装卸载数据保留检查通过。Desktop 退出夹具为测试自建进程，不操作真实用户 Docker；独立 WSL 成功/失败组合使用注入结果。实际 Linux Docker 门禁已通过资源预算/记录、项目与身份隔离、递归只读挂载、DNS/UDP/IPv6/宿主直连阻断、TLS/Reality/gRPC/QUIC 和固定链路故障、受限 HTTPS 请求、Chromium 内核沙箱及失败拒绝降级、中文 PTY、190 秒浏览器独立续期、双出口核验与异常停机。运行归档已在 containerd 和经典镜像存储导入后重复验证。[0.13.3 正式版](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.3-windows) 已公开发布，`draft=false`、`prerelease=false`，由 `/releases/latest` 确认 Latest；标签/来源提交为 `8c78678ce5a91a9653cff856c5e470cbf1639d8e`。公开安装包与便携包已经实际下载，大小、SHA-256 与 GitHub digest 一致；便携 ZIP CRC、两份 EXE 的固定版本 `0.13.3.0` 和正式版标志通过。额外只读解析两份 EXE 的 PyInstaller 模块表，确认都包含 `enge_spx.desktop_offline`、`desktop_shutdown` 和 `process_metrics`，避免只更新版本号却漏装修复。独立 WSL 状态组合使用注入结果，不能冒充在用户 Docker Desktop 4.99.0 / WSL2 设备上实际验收。

## 性能与边界

无常驻进程、轮询、监听端口或新增运行依赖；正常运行与管理接口可用时不进入新增 WSL 查询。失败路径每次独立证据最多两次只读 WSL 列表，单条子命令最多 3 秒，证据预算最多 8 秒，联合退出继续受原总时限约束；Engine 收尾后的复核重新取证。没有测量用户设备退出耗时或持续 CPU/内存变化，不声称提升百分比。

真实设备反馈尚待用户升级后确认；暂不处理既有终端偶发拒绝访问。保持未知状态可重试，不用不安全的跳过核验替代本修复。


## 公开附件核验

| 附件 | bytes | SHA-256 |
| --- | ---: | --- |
| `ENGE-SPX-Windows-x64-0.13.3-Setup.exe` | 34,384,697 | `a314207f8376aabce1ec8bcbd54948501601d9977a1eded79fbf8b1bacccca51` |
| `ENGE-SPX-Windows-x64-0.13.3-Portable.zip` | 52,930,249 | `93572aad3816e267709553dd28cb7ee8fdee4bdfb318ab3c6779afdbc0c4cd50` |
| `ENGE-SPX-Runtime-linux-amd64-0.13.3.tar.gz` | 875,949,180 | `a3e11593d2d59e1dcb9acd627d67ea5d3b65b95f67f53d67e7c14610e2584a98` |

公开 runtime manifest 的大小、SHA 与本次 CI 的实际导出一致，归档已在同次门禁的两种 Docker 存储导入验证，没有再次下载整份运行归档。配方仍为 gateway `9aa8a7818569`、work `6e3fcfa5633c`、browser `1bca0984bc51`，现有合规镜像可继续使用。
