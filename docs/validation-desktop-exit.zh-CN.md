# 可选联合退出交付与验证

基线 0.12.0，`221f59fddeab2570bf462c76cb4965c7fd2e8dd9`。源码候选及最终同次构建结果在完成后补记；跳过检查不计为通过。风险与文件方案见 [审计](desktop-exit-plan.zh-CN.md)。

## 1. 修改概述

新增默认关闭的联合退出设置。Windows 真正退出时可在本实例工作区核验停止、资源查询及性能记录保存后正常关闭 Docker Desktop。不改变 Engine 的本实例停止接口、X 隐藏或显式保留工作区退出，不增加生产依赖、权限、端口、镜像配方或许可证变更。

## 2. 源代码文件

`src/enge_spx/desktop_shutdown.py` 管理独立 schema=1 公开退出偏好、官方 CLI 调用、全流程超时和明确状态确认；`ui/controller.py` 串行收尾、异步关闭、失败重试与偏好保存；`ui/window.py` 增加控件及退出状态说明。`test_desktop_shutdown.py`、`test_exit_lifecycle.py`、`test_resource_recording_ui.py`、`test_window_frame.py` 覆盖核心及 Qt 顺序；`desktop_harness.py`、`test_gui_startup.py` 验证原生 Windows 源码/冻结进程；DPI、同机测量和发布门禁复用既有机制。

## 3. 核心架构与技术方案

```mermaid
flowchart LR
    P[用户保存联合退出偏好] --> E[真正停止并退出]
    E --> W[停止并核验本实例及后台服务]
    W --> R[等待采样取消及记录保存]
    R --> C{Windows 且已启用}
    C -->|否| Q[退出界面与托盘]
    C -->|是| D[本机 Desktop 正常关闭]
    D --> S{明确 stopped}
    S -->|是| Q
    S -->|失败或未知| F[保留窗口 重试或更改偏好]
```

Desktop 管理命令不带 Docker context，不注入工作区运行令牌；不使用 force、后台进程终止、WSL shutdown 或重启作为兜底。[官方 stop](https://docs.docker.com/reference/cli/docker/desktop/stop/) / [status](https://docs.docker.com/reference/cli/docker/desktop/status/) 支持同步停止和 JSON 状态；命令及后续确认均有界，连接失败不代表已关闭。

保存是独立后台操作，不构造或解密 Engine；权限失败不替换旧设置，排队退出随保存失败取消。关闭确认失败后，保留没有新 Engine 操作且运行状态仍停止的原核验结果；再次操作或运行记录改变时失效，避免重新启动 Docker 才能退出。偏好缺失默认为 false，旧程序忽略新文件，取消并保存即可回滚。

## 4. 已实现功能

默认未选中开关和显式保存、已保存/未保存反馈、菜单文字、X/保留工作区豁免、记录保存顺序、正常关闭/已关闭/停止中状态、超时/权限/旧版本失败保留界面及重试；明确说明会中断其它 Docker 工作负载。Linux 不执行 Windows Desktop 管理。不以关闭 Desktop 代替正常工作区停止。

## 5. 测试命令与实际结果

```bash
python tools/check_repository.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/smoke_gui.py
PYTHONPATH=src python tools/check_ui_dpi.py
python tests/test_gui_startup.py --packaged dist/ENGE-SPX/ENGE-SPX.exe
python tools/benchmark_p0.py --kind host --baseline 221f59fddeab2570bf462c76cb4965c7fd2e8dd9 --output host.json
```

本地 Linux ARM64 已发现 344 项，332 通过、12 项 Windows 专用跳过；200% 紧凑布局包括新控件通过。12 项关闭核心测试、退出生命周期、实际记录落盘后调用关闭及 Qt 控件保存等通过。原生 Windows 模拟进程、冻结程序及全部容器安全回归待云端补记；尚未操作用户真实 Docker Desktop。

## 6. 修改前后性能对比

默认不关闭，不新增轮询或常驻进程；仅在真正退出且已保存选择时增加有限管理调用。镜像配方与资源预算不变。宿主同机基线/候选三组交替及容器阶段结果待实际 CI 回填，不预设内存或速度改善比例。真实 Desktop 退出耗时、WSL2 缓存释放和磁盘增长仍须实机测量；独立模拟进程耗时不冒充真实 Desktop 性能。

## 7. 遗留问题

Windows CI 的管理进程夹具不能代替用户的真实 Desktop/WSL2、其它 Docker 任务、升级/资源节省状态和企业权限策略验收。关闭 Desktop 不删除/压缩虚拟磁盘，不保证其它 WSL2 缓存归零。旧管理接口不兼容时明确失败；Preview 未签名，也无独立安全审计。

## 8. 下一批任务

先使用实机记录完成真实 AI 任务和交互 noVNC 的长时测试，覆盖睡眠/唤醒、断网、Docker 重启和可选联合退出；依据真实瓶颈优化延迟、吞吐、内存及磁盘。物理设备/真实账号、签名和独立审计需要相应外部条件，不能以合成或 Linux 结果冒充。继续保留必要安全监测。
