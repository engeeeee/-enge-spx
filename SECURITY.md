# 安全报告

目前维护的版本为 **0.6.x Preview**，旧版问题原则上在当前版本修复；暂不承诺旧版本回补或响应时限。发布状态以 [Releases](https://github.com/engeeeee/ENGE-SPX/releases) 为准。

## 报告漏洞

优先使用仓库 **Security → Report a vulnerability** 提交私密报告；该入口需要仓库启用 private vulnerability reporting。如果入口不可用，请先提交只包含“请求私密安全报告渠道”的最小 Issue，不公开利用步骤、凭据、订阅地址或未修复漏洞细节，等待维护者提供合适渠道。仓库未提供可验证的公开安全邮箱。

私密报告可包含：受影响版本、Windows / Docker 版本、运行模式、复现条件、实际与预期行为、影响范围、已脱敏的最小样例，以及可能的缓解方式。不要使用他人的代理、账号或数据进行验证。

普通下载、启动或使用问题请按照 [SUPPORT.md](SUPPORT.md) 提交。

## 当前边界

请先阅读 [隔离与安全模型](docs/security-model.zh-CN.md)。容器、出口检查和异常停机都有明确范围；项目目录读写共享，代理凭据尚未接入系统凭据库加密，Chromium 目前使用 `--no-sandbox`。当前 Windows 包未代码签名，也未经过独立安全审计。

如发现敏感信息已公开，请尽快撤销相关凭据，并删除或编辑公开内容；仅删除消息不能保证已泄露凭据重新安全。
