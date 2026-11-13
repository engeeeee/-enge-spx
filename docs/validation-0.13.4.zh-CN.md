# 0.13.4 关闭竞态与退出诊断

## 问题与实施范围

反馈只提供了缺失 `dockerDesktopLinuxEngine` 管道的 Docker 错误，未取得客户端版本与核验日志，不能确定反馈设备的实际失败条件。源码另有可复现的关闭竞态：管道消失后，管理接口仍为 stopping 或已不可用，而进程/WSL 稍后才结束；0.13.3 对第一份未完成快照立即返回 False。

本批修复这条可复现路径，并将诊断入口放到失败弹窗中，避免重复要求用户找文件。未知状态仍保留界面，未实施跳过停止验证的退出方案。

## 文件与架构

- `desktop_shutdown.py`：在 12 秒上下文/管理观察预算内等待 stopping→stopped；其它明确活动状态不被离线证据覆盖。
- `desktop_offline.py`：在剩余时限内最多等待 8 秒，重复完整配置、进程、管道与 WSL 证据；接受规则与 0.13.3 一致，失败只增加固定阶段日志。
- `exit_diagnostics.py`：使用 ContextVar 隔离退出工作线程，最多 64 条只含固定代码与系统错误码的观察，不采集原始命令/错误输出或私人名称。
- `ui/controller.py`：只在失败时原子保存 schema-1 本地报告；保存失败不掩盖原错误。复制摘要不访问 Docker，配置不可读时提供最小版本与本次检查。
- `ui/window.py`：工作区停止未核实的弹窗直接显示运行版本并提供重试、复制、返回；默认返回，无隐式仅退出操作。Desktop 确认恢复窗口也增加复制。
- 复用 Desktop、退出生命周期、GUI、资源和打包测试，并补充报告隔离/脱敏、真实自建 Windows 进程退场及两类恢复弹窗的 DPI 检查。

没有配置逆迁移或既有数据变更。账号、代理、身份、预算、退出偏好和镜像继续兼容。`logs/exit-diagnostics.json` 只是诊断记录，不参与授权；旧版忽略此文件。

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_desktop*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_exit*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src QT_SCALE_FACTOR=2 python tools/check_ui_dpi.py
python tools/check_repository.py
node --test tests/test_release_publication.cjs
```

相同的模拟退场序列下，0.13.3 返回 False，候选的有界等待返回 True，且只在后续完整证据通过后成功。持续活动、重启、超时、权限不足、未知配置和不匹配上下文仍不能声称已停。本地 Linux ARM64 完整回归 415 项：399 通过、16 项 Windows 专用跳过，约 12.8 秒；9 项发布助手测试、Qt 200% 两种恢复弹窗/诊断按钮及 72 篇文档/版本检查通过。

[正式发布 CI #43342502482](https://github.com/engeeeee/ENGE-SPX/actions/runs/43342502482) 的 Linux、Windows、冻结包、容器及发布任务全部成功，发布源码为 `ac7927c3a43d1d7dfd9b138a0af5de1bd68a636d`。实际结果：

- Linux：415 项，399 通过、16 项平台专用跳过；Windows：415 项，411 通过、4 项跳过，约 98.9 秒。两个平台各有 9 项发布助手测试通过，跳过项不计通过。
- Windows 原生进程快照、独立命名管道、测试自有延迟退出进程与恢复弹窗复制 JSON 均通过；复制测试禁止访问 Docker。Qt smoke 及两类恢复弹窗在 125% / 150% / 200% DPI 下通过。
- 冻结包 GUI 手动启动、托盘、联合退出和 Docker 先关闭场景夹具、DPAPI、安装/卸载数据保留、PE 正式版本标志与 Python 3.12 打包检查通过。
- 容器门禁通过资源预算、记录、Profile 与只读挂载边界、迁移、DNS/UDP/IPv6 与宿主直连阻断、TLS/Reality/gRPC/QUIC 与固定链路失败检查、Chromium 原生沙箱及初始化失败拒绝启动、中文 PTY、190 秒浏览器活动期间的 guard 续期、出口核验和资源基线；运行环境归档在 containerd 与 classic 镜像存储下导入通过。

Windows 延迟进程测试只创建并等待测试自有 Docker Desktop.exe 夹具，使用真实 Win32 快照和独立管道；WSL 数据注入，不操作用户 Docker。此测试不能冒充反馈设备真实 Docker Desktop / WSL2 验收。

## 发布附件与下载复核

[0.13.4 正式版](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.4-windows) 已公开，非草稿、非预发布；标签指向上述源码，GitHub 最新正式版和官网下载入口均为 0.13.4。

| 附件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| Windows Setup | 34,395,291 | `1bab237db37abaed225ea2e229499046d9f66a849197b63cd4fcfc844f6630dd` |
| Windows Portable | 52,947,049 | `7606de9a5b53fc7c8c1288a241d06a8456a6294f6909612c94cafc3d6f93a605` |
| Runtime linux-amd64 | 875,934,645 | `b36e035973384c63fb898eab0d0898fc43d00790b33e7edfe25b9355eacdda7a` |

实际下载 Setup 和 Portable，确认字节数、公开校验文件、GitHub digest 与本地 SHA-256 一致，ZIP CRC 正确。解包后的 GUI/CLI 均为 `0.13.4.0` 正式 PE 版本，冻结归档包含 `exit_diagnostics`，并验证 `_observe`、`workspace-exit-copy`、`logs/exit-diagnostics.json` 等本批实现标记，避免只核对附件名称。运行环境不重复下载：公开清单、附件大小/digest 与同次 CI 导出及两种镜像存储导入证据一致。网关、CLI、浏览器配方分别仍为 `9aa8a7818569`、`6e3fcfa5633c`、`1bca0984bc51`。0.13.3 既有安装包和便携包校验值保持不变。

## 性能与限制

无常驻采集、额外监听、生产依赖或镜像配方变化。重试只在退出时发生，工作线程等待、不占用 GUI 线程；离线观察间隔 250 ms，具有原有证据预算，联合关闭保留原总时限。不降低安全监测频率。不声称 CPU、内存或退出速度的提升百分比，真实设备仍可能在未知后端、权限或配置状态上拒绝退出，此时直接复制的本地诊断用于后续定位。
