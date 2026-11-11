# 0.13.2 退出修复交付与验证

2026-11-11 已发布 [ENGE SPX 0.13.2 正式版](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.2-windows)，公开 `draft=false`、`prerelease=false`，由 `/releases/latest` 确认 Latest。发布提交/标签为 `762a210a3da1d3bb355b9024baca4e4891a22ba7`。本批仅处理 Docker Desktop 联合关闭超时、先关闭 Desktop 后软件无法退出；基线为 0.13.1 正式版及其验证文档提交 `8d00c1febe4b57e6c660184fc7c88bd97f6a16a5`。未执行或跳过的项目不算通过。

## 1. 修改概述

将 Desktop 关闭请求与状态等待分离，在明确的本机 Desktop 已停证据下允许离线收尾，并在仅 Desktop 确认失败时提供一次性“仅退出软件”恢复操作。保留工作区停止核验、后台锁等待、X 隐藏托盘和保存偏好的语义。

## 2. 涉及文件

`src/enge_spx/desktop_shutdown.py`、`engine.py`、`ui/controller.py`、`ui/window.py`；`tests/test_desktop_shutdown.py`、`test_exit_lifecycle.py`、`test_exit_recovery_ui.py`、`desktop_harness.py`、`test_gui_startup.py` 和 `tools/check_ui_dpi.py`。版本号、Windows 元数据、CI 资产名称、README、SECURITY、CHANGELOG、退出及发布文档同步更新。无生产依赖、容器配方或许可证变更。

## 3. 核心方案

`docker desktop stop --detach` 使用有界子命令，随后独立轮询 `desktop status --format json`，总时限仍为 60 秒。只在旧 CLI 明确拒绝 detach 参数时调用有界普通 stop。关闭过程管理接口暂不可读仍继续有界核验，状态始终未知时保留窗口；不强制结束 Desktop，不调用全局 WSL shutdown。

Daemon 无法访问时，仅在 context 元数据通过本地 IPC 验证、端点为精确的本机 Desktop Linux 管道且管理状态明确 stopped 后，允许清理运行时引用，等待 guard/forward/relay 锁并再次确认状态。远程端点、通用 docker_engine 管道、连接失败或未知状态不构成证据。Desktop 在最终核验前关闭的竞态也使用同一规则。

一次性退出仅在已取得工作区及后台停止结果、没有新 Engine 操作且运行记录仍明确 stopped 时可用。它不改写偏好，不宣称 Desktop 已关闭；失败对话框默认返回，恢复操作等对话框结束后再触发。

## 4. 已实现与兼容

两种退出顺序、异步正常关闭、旧 CLI 有界兼容、状态间隙核验、一次性退出和停止结果失效后的拒绝沿用均已有实现。数据格式不变，账号/代理/身份/项目权限/预算/镜像沿用；回滚到 0.13.1 无需配置逆迁移。按用户要求暂不处理偶发终端拒绝访问的问题。

## 5. 测试命令与实际结果

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_desktop_shutdown.py -v
PYTHONPATH=src python -m unittest discover -s tests -p test_exit_lifecycle.py -v
PYTHONPATH=src python -m unittest discover -s tests -p test_exit_recovery_ui.py -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/smoke_gui.py
QT_SCALE_FACTOR=2 PYTHONPATH=src python tools/check_ui_dpi.py
python tools/check_repository.py
node --test tests/test_release_publication.cjs
```

本地 Linux ARM64 专项 17 + 29 + 4 项通过；完整回归发现 383 项，370 通过、13 项 Windows 专用跳过。Qt smoke、200% DPI 的既有控件及新增恢复对话框、9 项发布助手测试、67 篇文档链接与版本元数据检查通过。跳过或未执行不算通过。

Windows 夹具仅启动测试自建的 Desktop.exe/CLI 进程，不操作用户 Docker。覆盖联合关闭开/关、X 隐藏与恢复、先手动正常关闭 Desktop 再退出以及账号/镜像保留，并在冻结 GUI 重新执行。

[最终同次完整 CI](https://github.com/engeeeee/ENGE-SPX/actions/runs/43052474557)全部通过：Windows 383 项（379 通过、4 跳过），Linux 383 项（370 通过、13 跳过），两平台各 9 项发布助手测试，Windows Qt smoke 和 125%/150%/200% 布局。Windows 源码与冻结 EXE 均通过联合关闭开/关、先关闭 Desktop 再退出、X 隐藏和恢复、默认停止及数据保留；冻结 CLI 的真实 DPAPI 迁移/删除、Python 3.12、两份 EXE 版本和正式标志、安装与卸载保留数据通过。恢复窗口截图已检查，默认返回。冻结 GUI 首屏记录 923 ms，仅为该次 runner 的观察。

实际 Docker 门禁通过资源预算/记录、Profile 和账号隔离、递归只读挂载、网络迁移与回滚、DNS/UDP/IPv6/宿主直连阻断、真实 TLS/Reality/gRPC/QUIC 与断线保护、受限 HTTPS 下载测试、Chromium 内核沙箱、沙箱失败不重试无沙箱、中文 PTY、190 秒浏览器独立续期、双出口核验和异常停机。导出归档在 containerd 与经典 Docker 镜像存储中重复导入、标签及数据保留均通过。测试不冒充真实 AI 账号或用户设备验收。

七个公开附件齐全，安装版与便携版已实际下载并核对大小、公开 SHA-256 和 GitHub digest；便携 ZIP CRC、必需资源、两份 EXE 的 PE 固定版本 `0.13.2.0` 与 flags=0 通过。旧 0.13.1 的附件 ID、大小、digest 和来源提交保留。

| 公开附件 | bytes | SHA-256 |
| --- | ---: | --- |
| `ENGE-SPX-Windows-x64-0.13.2-Setup.exe` | 32,458,407 | `164bb396448790e16ee19a48c49463891ed3e5f8b2d38c818ca3f59b02442ead` |
| `ENGE-SPX-Windows-x64-0.13.2-Portable.zip` | 50,982,025 | `a7eb50c9f95a0b243a6e22611e22e4033df2c0ca1ca616a3428c525d0cd80249` |
| `ENGE-SPX-Runtime-linux-amd64-0.13.2.tar.gz` | 875,916,707 | `6d9e267e3077abf88840d6128d274a100e4c8c94811d2c3f8ebb0bc3eb8133f4` |

公开 runtime manifest 的大小、SHA、平台与配方对照同次 CI 已导入两种存储的实际导出记录一致，没有再次下载整份运行归档。配方仍为 gateway `9aa8a7818569`、work `6e3fcfa5633c`、browser `1bca0984bc51`。

首次 Windows CI 的新增夹具绕过 Store 直接写明文 runtime，触发现有 DPAPI 格式保护，两个“先关闭 Desktop”子案例因日志中记录了拒绝明文的错误而失败；退出本身已完成。夹具改用实际 Store/DPAPI 和原子写入、读取解密后的状态，安全检查与生产逻辑不变，重新执行完整门禁。

## 6. 性能对比

没有新增常驻进程、轮询定时器、监听端口或运行依赖。正常使用期不发起新的 Desktop 管理查询，只在退出故障路径核验；异步关闭请求的 CLI 上限 12 秒，独立核验与旧版回退共用总 60 秒上限。实际关闭耗时依赖 Desktop，不能以单元测试推断用户机器提升。

同次 Linux Docker runner 依次运行 0.13.1（`e27f657`）正常、0.13.2 正常和低资源独立 worker，共用已验证的镜像。每阶段两份样本取均值，内存仅含本实例运行中容器的 Docker 统计，CPU 为单核百分比；不与宿主或 WSL2 内存相加。

| 观察 | 0.13.1 正常 | 0.13.2 正常 | 0.13.2 低资源 |
| --- | ---: | ---: | ---: |
| CLI 启动前容器内存（MiB） | 18.161 | 18.618 | 17.428 |
| 该阶段容器 CPU 合计（%） | 0.195 | 8.745 | 0.195 |
| 默认 CLI 启动后容器内存（MiB） | 249.393 | 246.473 | 18.485 |
| 该阶段容器 CPU 合计（%） | 0.390 | 0.365 | 0.040 |
| Chromium canvas 内存（MiB） | 284.184 | 278.989 | 284.791 |
| 该阶段容器 CPU 合计（%） | 24.040 | 28.070 | 31.990 |
| 默认 CLI 启动（ms） | 4,282.367 | 3,940.933 | 1,301.046 |
| 工作区完全停止（ms） | 647.889 | 920.012 | 529.580 |
| 完全停止后运行容器 / 内存 | 0 / 0 | 0 / 0 | 0 / 0 |

低资源模式原已延迟启动浏览器，CLI 阶段少一个浏览器，canvas 阶段已显式启动；不能归为本批节省。普通模式两版应用文件在完全停止后均为 918,795 B，低资源为 919,214 B；三组 project 可写层均为 8,413,184 B（含合成 8 MiB 写入），browser/session/gateway 层分别为 4,096/4,096/8,192 B，不代表卷或虚拟盘总量。

资源 artifact ZIP SHA 核验为 `aeea68eb2fe216a6b926f5e7d9f66499012d6fc1fa217f2dfb8da61cddbf2e40`。短样本会包含启动活动和缓存差异；本次正常模式的停止耗时比基线更长，CLI 前 CPU 也有瞬时活动，不能据此声称持续性能改善或退化。没有测得用户 Docker Desktop 的真实关闭时延；Windows 相关退出使用自建进程夹具。物理 Windows/WSL2 占用、GUI 长时空闲、真实 AI 与连接 noVNC 的持续负载未在此替代测量。

## 7. 遗留问题

无法确认 Desktop 状态或工作区停止失败时仍保留界面；不能安全地把未知状态当作已停止。用户本机 Docker Desktop/WSL2 的完整交互仍需使用反馈。终端偶发拒绝访问暂不改动；软件包未签名，未开展独立安全审计。

## 8. 后续任务

本版本完整 CI、正式发布与公开包校验均已完成。接下来根据实际使用反馈决定后续修复。终端问题如能复现，应单独收集脱敏证据并小范围处理，不与本批退出修复混合。
