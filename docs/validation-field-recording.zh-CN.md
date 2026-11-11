# 实机记录交付与验证

基线 0.11.0，`fdd319a`；当前为开发候选，最终构建结果须在此记录。风险和文件计划见 [审计方案](field-recording-plan.zh-CN.md)。

## 1. 修改概述

补充主动、有界的实机性能记录，并修复资源采样未提前核验本机上下文的缺口。不增加依赖、权限、监听端口、镜像配方、配置迁移或许可证变更。

## 2. 源文件

`resource_recording.py` 负责白名单、代号、统计、上限、中间文件和保存；`resource_monitor.py`、`docker_env.py`、`engine.py` 复用本机 IPC 校验，并用公开采样目标替代采样时的完整 Engine；`__main__.py` 提供前台记录；`ui/controller.py`、`ui/window.py` 处理独占采样、排队、托盘、退出和迁移；新增记录/上下文单元及 `integration_recording.py` 原生检查，并扩展 DPI、冻结 CLI 和既有 CI。

## 3. 技术方案

复用一个资源查询通道。用户主动记录期间普通刷新不重叠；活动是手选标签，不检查 AI 进程输入。脱敏后写私有中间记录，结束原子保存 JSON；保存失败保留原输出/中间文件及内存报告。真正退出等待采样和保存，数据迁移先收尾。异常、不支持和未运行与零占用区分。

本机上下文允许绝对 Unix socket 或 Windows `npipe:////./pipe/...` / `npipe://./pipe/...`，在任何 ps/info/stats 前核验，不连接 SSH/TCP 或远程命名管道。[Docker 官方连接形式](https://docs.docker.com/reference/cli/docker/#daemon-socket-option)。不改变当前上下文或主机网络。

## 4. 已实现

GUI 的独立记录标签、明确输出位置、1/5/15/60 分钟、状态/取消/再次导出；CLI 时长/间隔和 Ctrl+C；720 样本/4 MiB 上限；逐报告代号；应用、容器、宿主、Desktop/WSL 分类；不可用/截断/进程复用；当前采样或 GUI 操作结束后启动；最小化继续、真正退出/迁移前保存。见 [操作指南](field-recording.zh-CN.md)。

## 5. 测试命令与实际结果

```bash
python tools/check_repository.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/smoke_gui.py
PYTHONPATH=src python tools/check_ui_dpi.py
PYTHONPATH=src python tests/integration_recording.py --output native-recording.json
PYTHONPATH=src python tests/integration_recording.py --context default --output docker-recording.json
```

本地已通过记录核心、CLI 和 Qt 生命周期测试；原生 Linux 进程/宿主计数，以及真实无网络 Docker 的未启动→运行→停止记录、真实内存、另一实例排除与可写层保留已通过。最终跨平台、冻结程序和完整安全回归待云端验证后回填；不将本地 Linux 结果视为物理 Windows/WSL 验收。

## 6. 性能前后对比

默认不记录；原概览可见性规则不变。只有用户主动记录时增加采样、最多 4 MiB 的报告和有界内存缓冲，测量包含观察者开销；隐藏和托盘继续是该主动任务的行为。时间/CPU/内存及磁盘对照待同机测量，不预设改善比例。记录只读取计数，不减弱网络安全监测。

## 7. 遗留问题

物理 Windows/WSL2、真实 AI 账号的长期工作负载仍须用户设备验证；本工具提供采集能力，不是这些活动已通过的证明。离散采样可错过瞬时峰值；共享页/WSL 缓存不可简单相加。未签名 Preview 与独立安全审计的限制保持不变。

## 8. 下一批任务

依据真实设备记录处理明确的性能/兼容性问题，扩展有证据的验收覆盖；签名和独立安全审计需要相应条件。不为任何性能数字关闭 guard、放宽沙箱、修改全局 WSL 资源或开放直连。
