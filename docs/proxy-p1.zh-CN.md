# 0.9.0：代理协议、内部网络升级与托盘

本批保留 Python 3.12+、PySide6、Docker Desktop/WSL2，以及 0.8.4 的沙箱、DPAPI、双出口确认、租约、无 DIRECT 回退和数据持久化。没有新增生产依赖或代理核心。

## 后端和协议

继续使用现有 sing-box **1.14.3**，通过独立 `ProxyBackendAdapter` 生成固定链路。Engine 仍负责归属、网络、出口、租约和停止；导入配置不能覆盖这些控制。未实现的后端明确拒绝。Mihomo 已评估，当前通过转换其节点格式兼容，不额外安装另一个核心、控制器或升级服务。

| 节点 | 支持范围 |
| --- | --- |
| SOCKS5 / HTTP / HTTPS | 认证或无认证落地；HTTPS 保留证书和名称验证 |
| Shadowsocks | 既有 AEAD / 2022 TCP 配置 |
| VMess | AEAD TCP、可选 TLS，以及 WS/gRPC；未加密 VMess 不能作为加密第一跳 |
| Trojan | TLS TCP、WS、gRPC |
| VLESS | TLS TCP、WS、gRPC；Reality X25519 与 TCP `xtls-rprx-vision` |
| Hysteria2 | QUIC/UDP、TCP 与 UDP 目标载荷、固定服务器端口，可选 salamander |
| Clash/Mihomo | 常见 `proxies` YAML/JSON、URI 列表、Base64 列表和用户主动获取的 HTTPS 订阅 |

Reality 校验公钥编码和 32 字节长度、显式域名 SNI、short ID 的偶数位十六进制长度、flow/transport 组合。uTLS 仅用于协议 ClientHello 兼容，不宣称能隐藏或伪装浏览器身份。未知参数、XHTTP/KCP、多路复用、gRPC multi-mode、插件、跳端口和额外链路覆盖不在本批支持范围，不会剥掉后继续尝试。

WS/gRPC 保留路径、Host、服务名等已验证参数，并限制长度与控制字符。TLS 拒绝 `insecure` / `skip-cert-verify`；自定义 CA 只接受有界的内联 PEM，不读取导入配置指定的宿主机证书/私钥路径，不改系统信任库。CA 仅用于该节点的验证。

完整 Clash/Mihomo 配置只提取节点。其 DIRECT、分组、测速、故障回退、DNS 和远程 provider 不执行，并给出提示。仅含 provider 的配置应先通过订阅入口主动取得实际节点；软件不自动遍历其 URL。错误定位到条目和已知参数，不输出原节点、密码、UUID 或订阅令牌。

## Hysteria2 怎样接入

1. 导入 `hy2://` / `hysteria2://` 或相应 Clash/Mihomo 节点。
2. 单出口时可直接选择该节点；软件内双跳时将其选为加密第一跳，再选择 SOCKS5、HTTP 或 HTTPS 落地。
3. 第一跳使用域名时填写其服务器 IPv4，保留原 SNI 和证书验证。
4. 检查、分别核对第一跳与最终出口，然后确认启用。

Hysteria2 与服务器之间实际使用 QUIC/UDP，不会伪装成一个仅解析成功的 TCP 节点。单出口可通过既有 mixed/SOCKS 入口传递受控 UDP 载荷；CLI 和浏览器的 TCP 流量同样由 QUIC 承载。当前固定落地链路以 TCP 应用为目标，不声称 HTTP 落地能透明转发任意 UDP。

现有本机 HTTP/SOCKS 中转通过 TCP stdin 转发，不提供 QUIC UDP 承载。因此不能把 Hysteria2 当落地再套该中转，或套其它尚未验证的前置组合；保存时明确拒绝。可以保留 v2rayN 兼容模式使用现有 TCP 协议。系统 TUN 仍可能影响外层路由，不代表应用控制了它。UDP 不可达、密钥/认证失败或证书错误都保持失败，不自动切换 TCP、DIRECT 或备用节点。

## 自动升级旧网络

普通 Docker `internal` bridge 仍可能访问桥地址上的宿主服务。0.9.0 使用 `gateway_mode_ipv4=isolated` 移除该桥地址，保留内部代理通信；工作区仍无外部网卡，IPv6 不启用，session DNS 继续固定为容器回环地址。应用通过代理远程解析目标；忽略代理的程序会失败，不会因此获得直连。

首次检测或准备时，软件先撤销租约并停止本实例容器，然后重建同名内部网络、恢复原子网和固定地址。项目与 session 容器 ID、可写层、工具账号、浏览器 Profile 和下载卷保留，不执行 Docker prune，不修改宿主全局 sysctl、LSM 或安全策略。发现外部资源占用时拒绝迁移，不断开其它用户资源。

`network-upgrade.json` 是版本 **1** 的非敏感迁移记录，保存网络元数据和关联容器地址。记录先写入，再变更网络。中断后继续恢复；连接失败会尝试恢复原网络元数据，所有容器保持停止，绝不启动旧策略兜底。恢复也失败时保留记录和原数据，提示重试。不要在迁移期间手动删除记录或 Docker 资源。

升级需重新核对出口，旧确认结果不能沿用。原 0.8.4 合格镜像配方、节点 ID、DPAPI 封套、账号和卷名保持兼容，无需因为协议增加而删除数据。需要回滚时先停止环境，保留数据和 Docker 备份，再运行旧程序并选择其支持的节点重新检查；旧程序无法使用新增协议。0.8.3+ 使用相同 DPAPI 封套，更早版本需遵循 [显式凭据导出流程](security-hardening.zh-CN.md)。

重新检查还会自动等待旧后台监测退出，防止旧策略误停新会话。旧版监测最多需要约 40 秒交接，界面会显示等待原因；新监测收到停止信号后会尽快退出，正常网络复核频率不变。不要同时运行两个版本操作同一数据目录。

## 关闭窗口与退出

Windows 系统托盘可用时，标题栏 X 只隐藏窗口；下载、工作区和网络监测继续运行。单击/双击托盘图标或再次打开软件可恢复主窗口。

托盘右键提供“显示主窗口”“退出界面（保留工作区）”和“停止工作区并退出”。保留工作区时，独立 guard 继续维护租约与异常停机；停止并退出只停止本实例资源，不关闭 Docker Desktop 或其它软件的容器。停止期间会等待正在进行的安全检查。操作进行中不强制中断不可取消的任务；没有可用托盘时保留正常关闭，避免留下无法操作的隐藏界面。

## 验证和边界

见 [源码、实际测试与性能记录](validation-p1.zh-CN.md)。内核沙箱要求和 Windows 用户 DPAPI 边界不变；Docker 管理员、同账户恶意代码、线路服务商和外部 v2ray 分流不受应用完全控制。不提供匿名、账号可用或不可识别保证。

参考：[sing-box Hysteria2](https://sing-box.sagernet.org/configuration/outbound/hysteria2/)、[TLS/Reality](https://sing-box.sagernet.org/configuration/shared/tls/)、[V2Ray transports](https://sing-box.sagernet.org/configuration/shared/v2ray-transport/)、[Docker gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)。
