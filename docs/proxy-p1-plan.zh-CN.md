# 第二批：代理后端、协议与网络边界

起点：已发布的 0.8.3，主分支提交 `254f37832da66f674ff0939bf8e84a8055f92479`。
第一批的沙箱、DPAPI、租约和数据持久化继续作为约束，不引入权限或 TLS 降级。

## 后端选择

| 方案 | 能力和依赖 | 本批选择 |
| --- | --- | --- |
| 已有 sing-box 1.14.3 | 已随网关交付；目标 Reality、WS、gRPC 和 Hysteria2 均有实现；官方原生二进制实际报告 with_quic / with_utls | 先抽出独立适配层，复用已有核心与许可证义务，实测 Docker 版本标签和所有协议 |
| Mihomo | 常见 Clash/Mihomo 格式更接近其配置，但需新增可执行文件、下载校验、升级路径、管理接口约束和独立集成矩阵 | 本批保留适配扩展位置，先把 YAML 节点转换为既有规范数据；不加载其 DIRECT/自动选择策略 |

适配层保留现有规范节点、节点 ID 和 JSON 配置格式，负责能力描述、固定链路配置生成及 UDP 组合校验；出口确认、拓扑审计、租约和停机继续由现有 Engine 控制。未实现的后端明确拒绝，不能自动换后端或直连。

## 文件级顺序

1. `tools/probe_proxy_network.py`、独立 P1 CI：验证核心编译标签、内部网络的宿主服务边界，以及不更换 session/project ID 的 isolated bridge 迁移可行性。
2. `backends/` 与 `engine.py`：先抽出已有 sing-box 配置生成，旧配置生成结果和节点 ID 保持一致；用单元回归核对，再扩展能力。
3. `nodes.py`、新增参数验证模块：增加 Reality、WS/gRPC、Hysteria2、常见 Clash/Mihomo 节点与订阅解析。错误定位到已知参数，不能输出凭据。未知行为参数明确拒绝；不执行导入配置的规则、控制器或远程 provider。
4. 仅在网络探针确认后调整 `engine.networks/audit_topology`：若需升级 bridge 策略，必须先停止旧资源；保留项目容器和可写层，失败时恢复停止状态的原网络记录，不能启动旧弱策略兜底。
5. `tests/integration_protocols.py`：使用受控 TLS/Reality/QUIC 服务端与合成凭据，测试真实握手、HTTP 和必要 UDP 数据路径、固定线路/落地、错误密钥、错误证书、断线和 UDP 故障。TLS 测试只显式信任临时 CA，不关闭校验。
6. Docker 防泄漏集成：分别记录工作容器、网关、第一跳、最终服务；实际阻断 DNS/UDP/IPv6 绕行，保留 v2rayN 兼容路径和现有全部回归。
7. 完成代码、Windows/容器测试、兼容迁移与文档后，才将新协议列为已支持；保留每种组合的限制。

## 重点约束与风险

- Reality 必须验证 X25519 公钥编码/长度、SNI、short ID 和可用的 flow/transport 组合。uTLS 参数用于协议兼容，不宣称不可识别。
- Hysteria2 的 TCP/UDP 目标流量最终通过 QUIC/UDP 传输；必须实测 UDP 承载和 UDP 故障。现有本机 stdin 转发是 TCP，不能把不支持 UDP 的 HTTP/TCP 前置误当作 QUIC 通道；此类不兼容组合需在启动前拒绝。
- Docker 官方文档说明普通 internal bridge 仍可能访问桥地址上的宿主服务；isolated 模式移除桥地址。先用临时 TCP/UDP 宿主夹具验证，再决定迁移，不能只靠 `Internal=true` 声称阻断了全部旁路。
- Docker 26 已修复 internal-only 网络的外部 DNS 转发问题，项目要求 Engine 28+。本批仍需实际验证系统 DNS、显式 DNS、UDP 和 IPv6，不能把没有直连默认路由当作全部证据。
- CLI/浏览器文件与 PID 隔离、固定落地、无 DIRECT、双出口和认证失败关闭保持；不新增常驻宿主监听端口，不增加容器 capabilities。
- 复杂度高的部分是网络兼容迁移与真实 QUIC 故障注入。仅解析分享链接不构成协议验收，证书自签测试也不能冒充公开 CA 的用户环境验收。

## 依据

- [sing-box Hysteria2](https://sing-box.sagernet.org/configuration/outbound/hysteria2/)
- [sing-box TLS / Reality](https://sing-box.sagernet.org/configuration/shared/tls/)
- [sing-box V2Ray transport](https://sing-box.sagernet.org/configuration/shared/v2ray-transport/)
- [Mihomo VLESS](https://wiki.metacubex.one/config/proxies/vless/)
- [Docker gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)
- [Docker Engine 26 DNS 修复](https://docs.docker.com/engine/release-notes/26.0/)
