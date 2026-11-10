# 安全报告

目前维护 **0.9.0 Preview**；已发布版本和安装包状态以 [Releases](https://github.com/engeeeee/ENGE-SPX/releases) 为准。0.8.3 包含第一批 P0 沙箱与凭据保护改造，使用旧 0.8.2 包不会获得这些改动。暂不承诺旧版本回补或响应时限。

## 报告漏洞

优先使用仓库 **Security → Report a vulnerability** 提交私密报告；该入口需要仓库启用 private vulnerability reporting。如果入口不可用，请先提交只包含“请求私密安全报告渠道”的最小 Issue，不公开利用步骤、凭据、订阅地址或未修复漏洞细节，等待维护者提供合适渠道。仓库未提供可验证的公开安全邮箱。

私密报告可包含：受影响版本、Windows / Docker 版本、运行模式、复现条件、实际与预期行为、影响范围、已脱敏的最小样例，以及可能的缓解方式。不要使用他人的代理、账号或数据进行验证。

普通下载、启动或使用问题请按照 [SUPPORT.md](SUPPORT.md) 提交。

## 当前边界

请先阅读 [隔离与安全模型](docs/security-model.zh-CN.md)及 [P0 升级与恢复](docs/security-hardening.zh-CN.md)。0.8.3 起强制验证 Chromium 的 user namespace 与 Seccomp-BPF 沙箱；不能初始化时拒绝浏览器启动，不添加容器特权或无沙箱回退。Windows 的应用代理配置使用当前用户 DPAPI 保护，容器通过 stdin 接收运行时凭据。

项目仍为读写共享，工具账号及浏览器资料仍默认在项目间共享。DPAPI 不能防止同一 Windows 账户下的恶意程序、管理员或 Docker 管理者读取运行时凭据；CLI 账号卷和浏览器 Profile 不属于本批 DPAPI 加密范围。Linux 使用私有文件权限，不能宣称已加密。当前 Windows 包未代码签名，也未经过独立安全审计。

如发现敏感信息已公开，请尽快撤销相关凭据，并删除或编辑公开内容；仅删除消息不能保证已泄露凭据重新安全。

0.9.0 将内部 bridge 升级为 isolated 模式，保留容器与可写层，并用版本化记录恢复中断；迁移失败保持停止。新增协议不接受跳过 TLS 校验、导入的 DIRECT/自动选择规则或外部 provider 执行。Hysteria2 使用真实 QUIC/UDP；不兼容的 TCP 前置组合在保存设置时拒绝。完整限制见 [第二批协议与迁移](docs/proxy-p1.zh-CN.md)。
