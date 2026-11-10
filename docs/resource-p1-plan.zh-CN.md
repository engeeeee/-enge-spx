# 第三批：资源管理与性能

基线为 0.9.0，`1de64dd76a61ac4fa5f86e28f5bae10a964aced9`。保留 P0/P1 的沙箱、DPAPI、isolated 网络、双出口、租约与异常停机，不修改 Docker/WSL 全局配置。

## 审计与实施顺序

| 文件 | 现有能力与问题 | 增量改造、风险与依赖 |
| --- | --- | --- |
| `engine.py` | 已复用镜像/session/project；session 128 MiB、project 4 GiB、browser 2 GiB 写死，CPU 未限制；工具会连带启动浏览器 | 新增版本化资源预算，在停止状态用 Docker update 应用并复用原 ID/可写层。降低内存可能使工具 OOM，保存前提示并先停止环境；失败保持停止 |
| `resource_limits.py`（新增） | 无集中配置与逐项目预算 | 正常/低资源/自定义、角色与项目校验、创建参数、停止状态更新；旧配置缺省仍沿用 0.9.0 上限；schema=1 与上次设置恢复 |
| `process_metrics.py`（新增） | 无宿主/后台进程资源归属记录 | 标准库 Win32 API / Linux proc；只记录后台动作、PID 和创建标识，不读取命令行；采样失败不干扰 guard |
| `resource_monitor.py`（新增） | 无容器 CPU、内存、磁盘 I/O 展示 | 一次只读 Docker stats 覆盖本实例运行容器，有限输出；应用、Desktop、WSL2 分开展示，明确共享与权限不足，不能将重叠计数相加 |
| `ui/controller.py`、`ui/window.py` | 页面懒加载、异步工作与托盘已存在，UI 状态每 1.5 秒刷新 | 新资源页与预算表单；仅资源页可见时异步采样，单任务不重叠；隐藏/最小化减少 UI 刷新，独立安全监测不变 |
| `engine.py`、`relay.py`、CLI | 浏览器按需创建但工具默认拉起；显示连接可复用 | 显式自动浏览器开关，登录按钮仍可启动；单独停止浏览器和显示服务，保留 CLI 与 Profile；不回退宿主浏览器 |
| `tests/`、`tools/benchmark_resources.py` | 既有 202 单元、真实协议/网络/长时/打包门禁 | 覆盖预算失败与复用、独立项目、采样生命周期、真实 cgroup/浏览器停止。分阶段记录同机前后数据，不把合成负载冒充真实 AI 服务活动 |

## 默认与边界

正常模式保持旧内存上限与不限 CPU；低资源模式显式选择后生效。保存预算先停止本实例工作区，下一次检查/启动应用；不会杀其它容器、关闭 Desktop、执行 WSL shutdown、prune 或回收用户文件。资源设置不改变网络策略，不降低 guard 的检查频率。

可行性实测发现 Docker update 的 memory=0 表示不更新，不能清除已有内存上限。故项目/session/浏览器使用有限内存预算，禁止以重建项目来清除限制；仅恢复网关不限内存时替换已停止、不保存用户数据的网关。网关固定地址和受控网络按既有 setup 重建并重新核验，不沿用旧确认。

资源 schema=1 是旧 settings 的可选字段，缺失不写入或重置旧数据。上次有效资源设置另存为非敏感回滚记录。低资源不等于保证更快，CPU 限额可能降低编译速度，内存限额可能终止进程。

采样只展示证据：Docker CLI 的 Linux 内存读数已减去部分缓存；WSL2 包含容器和其它发行版，不属于本应用独占。Windows 查询失败时显示不可用，不要求管理员权限。CLI、后台服务、Linux 容器和主机整体分别记录，关闭 GUI 不代表 WSL2 立即归还全部缓存。

本批不实现多身份 Profile 或指纹调整。没有新增生产依赖；PolyForm Noncommercial 与第三方声明不变。

参考：[Docker 资源约束](https://docs.docker.com/engine/containers/resource_constraints/)、[停止容器的资源更新](https://docs.docker.com/reference/cli/docker/container/update/)、[Docker stats 口径](https://docs.docker.com/reference/cli/docker/container/stats/)、[Win32 进程快照](https://learn.microsoft.com/en-us/windows/win32/toolhelp/snapshots-of-the-system)。
