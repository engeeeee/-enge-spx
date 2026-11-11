# 有界网络测量：审计与实施方案

基线为 0.12.1，`04b64bb`。本批为按需采集证据，不自动切换代理、修改分流或以关闭安全机制换取速度；不声称已完成物理 Windows/WSL2 的长期验收。

## 已有实现与真实缺口

- `network_diagnostics.py` / `Engine.ready(timings=...)` 已有第一跳和最终出口复核耗时；它包含多个 HTTPS 请求，不能当作 RTT 或下载吞吐量。
- 工作区通过 session 的受控网关访问外部。第一跳诊断只在 gateway 回环可见，保持这一边界，不向工作容器增加前置测速代理或 DIRECT。
- Qt 资源记录、退出顺序和可选关闭 Desktop 已存在。本批复用工作线程和导出，测量期间正常 guard 继续运行，普通网络检查不自动消耗测速流量。

## 文件级实施与风险

| 文件 | 方案与风险 |
| --- | --- |
| `resources/checks/network_probe.py` | 标准库 HTTPS CONNECT 客户端，仅连接已核验内部网关 IP；固定 Cloudflare HTTPS 下载目标，2 次小请求 + 1 MiB 下载，最多 3 请求、约 1 MiB 应用载荷、15 秒测量预算；拒绝重定向/编码异常/多余载荷，保持证书/名称验证。Linux 子进程硬超时，不添加依赖。高风险，需真实 TLS/代理/慢响应测试 |
| `network_performance.py`、`engine.py` | 独立按需入口，前后双出口核验，长测量阶段释放操作锁让 guard 运行；比较会话/策略/确认身份，变化时丢弃结果且不停止新会话。只导出白名单计数，调用参数经 stdin。高风险 |
| `__main__.py`、`ui/controller.py`、`ui/window.py` | 新 CLI 和网络页主动按钮，流量/服务/范围说明；首次运行不自动测试，不启动 Docker/浏览器，不导出旧任务冒充新结果；真正退出排队等待测量收尾。中风险 |
| 单元、真实 TLS/CONNECT 与 Docker 集成 | 代理必经、TLS/名称/重定向/载荷/超时失败、NO_PROXY 无效、前后出口/切换竞态、不阻塞 guard、无新增监听、冻结资源与 0.12.1 回归 |
| 操作/验收/验证文档及 CI | 记录准确单位、请求范围和实际结果；补 Windows/WSL2 长时使用、睡眠唤醒、Docker 重启、真实 AI/noVNC 的人工验收步骤。没有实机证据的项目保持待验收 |

只有最终受控链路进行下载测量；第一跳保持既有出口复核耗时，不用两者相减推断线路瓶颈。目标服务拒绝、限流或超时产生失败/不完整样本，不触发直连；TLS 证书验证失败、前后出口或拓扑复核失败会请求并核验本实例停止。用户/其它进程已切换会话时不据旧测量停止新会话。

没有持久配置格式或镜像配方变更，不新增权限/端口/依赖或后台轮询；升级/回滚保留原账号、代理、预算和 Desktop 退出偏好。

依据：[Cloudflare 官方测量端点](https://github.com/cloudflare/speedtest)、[Python HTTPS CONNECT](https://docs.python.org/3.12/library/http.client.html#http.client.HTTPConnection.set_tunnel)、[Linux 子进程定时器](https://docs.python.org/3.12/library/signal.html#signal.setitimer)。不集成该测速 SDK，不发送其测量结果遥测；固定目标服务仍可观察最终出口和这次 HTTPS 请求。
