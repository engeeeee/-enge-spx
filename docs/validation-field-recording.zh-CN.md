# 实机记录交付与验证

基线 0.11.0，`fdd319a4cf7947c9d8952ac752c12c721fb2d226`；源码候选 `ef91ad8`。最终发布须通过主分支同次构建的完整门禁；跳过的检查不计为通过。风险和文件计划见 [审计方案](field-recording-plan.zh-CN.md)。

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
python tools/benchmark_p0.py --kind host --baseline fdd319a4cf7947c9d8952ac752c12c721fb2d226 --output host.json
PYTHONPATH=src python tools/benchmark_resources.py --baseline fdd319a4cf7947c9d8952ac752c12c721fb2d226 --context default --runtime-report integration-results.json --output resources-docker.json
```

源码候选的 [实机记录专项 CI](https://github.com/engeeeee/ENGE-SPX/actions/runs/42967203243) 三个任务全部成功。Windows 319 项（315 通过、4 项 Linux 专用跳过），Linux 319 项（308 通过、11 项 Windows 专用跳过）；两平台真实进程/宿主计数与 CPU 差值记录通过，未启动或查询 Docker、未修改配置和运行状态。真实 Linux Docker 三项场景通过：所属容器未启动→运行→停止，运行中存在非零内存计数；另一实例被排除且继续运行；观察没有重启容器或删除可写层，报告脱敏并清理已完成的中间文件。活动使用合成进程，未声称执行真实 AI 任务。

本地 Linux ARM64 同样通过 319 项（308 通过、11 项平台跳过）、GUI/200% 紧凑布局与上述真实 Docker 场景，专用测试 daemon 已停止。[完整回归](https://github.com/engeeeee/ENGE-SPX/actions/runs/42967291521) 的两平台测试、125/150/200% DPI、冻结 Python 3.12 CLI 的实际五秒记录、真实 DPAPI 迁移/显式回滚/删除、GUI 手动启动 Docker、托盘/真正退出、安装卸载保留数据均已通过。冻结 GUI 此次首绘为 786 ms，无同条件旧安装包对照，不作为提速证据。

完整 PR 回归已全部通过，包括真实 cgroup 限额/数据复用、三项记录场景、身份数据/递归只读、停止后网络迁移/回滚及 DNS/UDP/IPv6 阻断；TLS、Reality、gRPC、QUIC 协议夹具；实际 Chromium namespace/PID/network/seccomp 与 renderer 内核证据、中文 PTY、无中文系统字体、190 秒无 shell 输入续期、过期租约关闭、独立停止/恢复浏览器与 Cookie/Storage 保留、数据搬迁、全部归属服务停止、沙箱失败拒绝启动。真实线路与落地双跳、独立出口变化、Hysteria2 QUIC/UDP 故障均按 Fail-Closed 工作；七项真实 Chromium 身份/诊断场景与全部资源测量阶段成功。

上述合成账号与本地 OAuth/Cookie 夹具不代表真实 AI 登录，云端 Windows Server 也不代表物理 Windows/WSL 验收。PR 按规则跳过镜像导出、两种镜像存储导入和发布；这些不计入 PR 通过项。主分支将重新运行全部测试并增加同次制品的双存储导入，只有全部成功才发布；实际结果与公开资产核验在完成后补记。源码与测试不因最终文档补记而更改。

## 6. 性能前后对比

默认不记录；原概览可见性规则不变。只有用户主动记录时增加采样、最多 4 MiB 的最终报告和有界缓冲；隐藏和托盘继续是该主动任务的行为。记录读取计数，不减弱网络安全监测。写入失败保留的私有中间文件也会占用磁盘，不自动删除未成功保存的证据。

同一专项 CI、Python 3.12、默认共享模式与 20 个合成节点，三组 baseline/candidate 交替次序；下表为中位数。GUI 空闲每组约五秒，CPU 为单核百分比，工作集是测量结束时的 OS 计数：

| 指标 | Windows 0.11.0 → 候选 | Linux 0.11.0 → 候选 |
| --- | --- | --- |
| GUI 导入/构造/首次绘制 | 294.449 → 229.082 ms | 185.721 → 152.323 ms |
| GUI 空闲 CPU | 0.6123% → 0.6005% | 0.3376% → 0.3620% |
| GUI 工作集 | 83.88 → 82.96 MiB | 91.04 → 90.36 MiB |
| 合成默认配置持久数据 | 7,902 → 7,902 B | 6,794 → 6,794 B |

短样本受 VM、调度、工作集回收和冷暖缓存影响。基线来自新解压的源码归档，候选来自已运行测试的工作树，字节码/文件缓存条件可能不同；首绘差异不能独立归因于代码提速。Linux 空闲 CPU 略增，不能据此声称资源全面下降。不推导固定改善比例。

宿主对照未启动 Docker，也未开启新记录任务，不能说明主动记录的额外开销。真实记录本身包含观察者成本；六秒宿主和二十秒 Docker 生命周期测试只验证记录机制，未隔离测量长期主动采样成本。

同一完整 PR 的 Linux Docker runner，依次执行三个独立 worker，分别采用 0.11.0 正常、候选正常和候选低资源设置；复用同批已核验镜像和同一只读观察器，使用各自临时数据。每阶段两次 Docker stats 的所属运行容器总和均值，减去部分缓存；不是 WSL2 全机内存：

| 容器阶段/内存 MiB | 0.11.0 正常 | 候选正常 | 候选低资源 |
| --- | ---: | ---: | ---: |
| 工具启动前，网关/会话 | 18.20 | 17.89 | 17.85 |
| 默认工具容器启动后空闲 | 249.57 | 250.42 | 18.15 |
| 合成 CPU/磁盘活动 | 254.46 | 253.88 | 25.62 |
| 显式 Chromium canvas 活动 | 280.84 | 280.84 | 282.24 |
| 单独停止浏览器，保留 CLI | 29.55 | 29.75 | 28.34 |
| 完全停止 | 0 个运行容器 | 0 个运行容器 | 0 个运行容器 |

正常模式没有明显内存下降。低资源空闲值较低来自既有浏览器懒启动；本次未改变容器资源策略或镜像配方。合成双哈希线程 CPU 总和约 200.97% / 200.82% / 100.61%，符合原有一核限额，不代表真实模型延迟改善。

工具容器准备为 2.80 / 2.84 / 0.80 秒；低资源首次显式打开浏览器为 4.30 秒，前两组已运行浏览器操作为 0.53 / 0.51 秒，不是同条件冷启动对照。离线 `claude --version` 三次启动中位数为 8.68 / 9.53 / 8.75 ms，`codex --version` 为 30.16 / 32.30 / 29.88 ms，未测真实交互、网络模型请求或编译。

三组项目可写层同为 8,413,184 B（包含合成 8 MiB 文件）；浏览器 Profile 采样为 10,316,367 / 10,316,384 / 6,082,569 B，时点和缓存不同，不代表压缩效果。全部停止后应用数据为 918,793 / 918,795 / 919,214 B，不含全部 Docker 卷/虚拟磁盘。停止只证明本实例无运行容器，Desktop、WSL2 或系统缓存不必归零，也不会被强制关闭。原始 JSON 位于上述 CI 的 Resource-Measurements 与 Field-native-* Artifact。

## 7. 遗留问题

物理 Windows/WSL2、真实 AI 账号的长期工作负载仍须用户设备验证；本工具提供采集能力，不是这些活动已通过的证明。原生 Windows runner 未运行 Docker Desktop/WSL2，其对应组没有可用样本，不能当作已测得零占用。离散采样可错过瞬时峰值；共享页/WSL 缓存不可简单相加。未签名 Preview 与独立安全审计的限制保持不变。

## 8. 下一批任务

依据真实设备记录处理明确的性能/兼容性问题，扩展有证据的验收覆盖；签名和独立安全审计需要相应条件。不为任何性能数字关闭 guard、放宽沙箱、修改全局 WSL 资源或开放直连。
