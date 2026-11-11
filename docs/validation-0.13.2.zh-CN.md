# 0.13.2 退出修复交付与验证

本批仅处理 Docker Desktop 联合关闭超时、先关闭 Desktop 后软件无法退出。基线为 0.13.1 正式版及其验证文档提交 `8d00c1febe4b57e6c660184fc7c88bd97f6a16a5`。发布前先运行完整门禁；以下明确区分已执行和待执行项目。

## 1. 修改概述

将 Desktop 关闭请求与状态等待分离，在明确的本机 Desktop 已停证据下允许离线收尾，并在仅 Desktop 确认失败时提供一次性 app-only 恢复操作。保留工作区停止核验、后台锁等待、X 隐藏托盘和保存偏好的语义。

## 2. 涉及文件

`src/enge_spx/desktop_shutdown.py`、`engine.py`、`ui/controller.py`、`ui/window.py`；`tests/test_desktop_shutdown.py`、`test_exit_lifecycle.py`、`test_exit_recovery_ui.py`、`desktop_harness.py`、`test_gui_startup.py` 和 `tools/check_ui_dpi.py`。版本号、Windows 元数据、CI 资产名称、README、SECURITY、CHANGELOG、退出及发布文档同步更新。无生产依赖、容器配方或许可证变更。

## 3. 核心方案

`docker desktop stop --detach` 使用有界子命令，随后独立轮询 `desktop status --format json`，总时限仍为 60 秒。只在旧 CLI 明确拒绝 detach 参数时调用有界普通 stop。关闭过程管理接口暂不可读仍继续有界核验，状态始终未知时保留窗口；不强制结束 Desktop，不调用全局 WSL shutdown。

Daemon 无法访问时，仅在 context 元数据通过本地 IPC 验证、端点为精确的本机 Desktop Linux 管道且管理状态明确 stopped 后，允许清理运行时引用，等待 guard/forward/relay 锁并再次确认状态。远程端点、通用 docker_engine 管道、连接失败或未知状态不构成证据。Desktop 在最终核验前关闭的竞态也使用同一规则。

一次性退出仅在已取得工作区及后台停止结果、没有新 Engine 操作且运行记录仍明确 stopped 时可用。它不改写偏好，不宣称 Desktop 已关闭；失败对话框默认返回，恢复操作等对话框结束后再触发。

## 4. 已实现与兼容

两种退出顺序、异步正常关闭、旧 CLI 有界兼容、状态间隙核验、一次性退出及失效证明拒绝均已有实现。数据格式不变，账号/代理/身份/项目权限/预算/镜像沿用；回滚到 0.13.1 无需配置逆迁移。按用户要求暂不处理偶发终端拒绝访问的问题。

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

本地 Linux ARM64 专项 17 + 29 + 4 项通过；完整回归发现 383 项，370 通过、13 项 Windows 专用跳过。Qt smoke、200% DPI 的既有控件及新增恢复对话框、9 项发布助手测试、67 篇文档链接与版本元数据检查通过。Windows 原生/冻结程序、安装卸载、实际 Docker 协议/隔离/沙箱和导出归档门禁待同次 CI 执行后补充；跳过或未执行不算通过。

Windows 夹具仅启动测试自建的 Desktop.exe/CLI 进程，不操作用户 Docker。覆盖联合关闭开/关、X 隐藏与恢复、先手动正常关闭 Desktop 再退出以及账号/镜像保留，并在冻结 GUI 重新执行。

首次 Windows CI 的新增夹具绕过 Store 直接写明文 runtime，触发现有 DPAPI 格式保护，两个“先关闭 Desktop”子案例因日志中记录了拒绝明文的错误而失败；退出本身已完成。夹具改用实际 Store/DPAPI 和原子写入、读取解密后的状态，安全检查与生产逻辑不变，重新执行完整门禁。

## 6. 性能对比

没有新增常驻进程、轮询定时器、监听端口或运行依赖。正常使用期不发起新的 Desktop 管理查询，只在退出故障路径核验；异步关闭请求的 CLI 上限 12 秒，独立核验与旧版回退共用总 60 秒上限。实际关闭耗时依赖 Desktop，不能以单元测试推断用户机器提升。

同次 Docker runner 将比较 0.13.1、0.13.2 正常及低资源阶段，CPU/内存/启动/停止与磁盘结果待执行后填入。物理 Windows/WSL2 占用、真实 AI 或已连接 noVNC 长时负载不由该基准代替。

## 7. 遗留问题

无法确认 Desktop 状态或工作区停止失败时仍保留界面；不能安全地把未知状态当作已停止。用户本机 Docker Desktop/WSL2 的完整交互仍需使用反馈。终端偶发拒绝访问暂不改动；软件包未签名，未开展独立安全审计。

## 8. 后续任务

先完成本版本完整 CI、正式发布与公开包校验，再根据实际使用反馈决定后续修复。终端问题如能复现，应单独收集脱敏证据并小范围处理，不与本批退出修复混合。
