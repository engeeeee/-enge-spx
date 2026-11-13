# Codex / Claude 更新与终端

从 0.13.5 起，通过软件打开的工具以及 `spx codex`、`spx claude`、`spx shell`、`spx exec` 使用当前身份的持久化用户前缀 `~/.local`。不需要以 root 运行、不修改系统目录权限，也不需要重新构建镜像。已有账号、项目、容器可写层和 Profile 卷保留。

## 更新与重新启动

Codex 内置更新调用 npm 全局安装；`NPM_CONFIG_PREFIX` 和 `npm_config_prefix` 指向 `/home/workspace/.local`，其 `bin` 目录优先于镜像内的系统安装。更新请求沿用当前已确认的受控代理。也可以在软件打开的 Linux 终端中显式执行：

```bash
npm install -g @openai/codex@latest
codex --version
```

Claude 可使用其内置更新或 `claude update`。使用 npm 安装的用户也可以显式执行：

```bash
npm install -g --allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code@latest
claude --version
```

这里仅允许 Claude 官方包必需的安装脚本，不全局放开所有包的脚本。Claude 原生安装会使用自己的用户版本目录；具体更新渠道、版本和安装策略仍由工具自身管理，不会在 ENGE SPX 启动时额外强制安装 latest。官方行为见 [Codex CLI](https://developers.openai.com/codex/cli) 和 [Claude 安装/更新](https://code.claude.com/docs/en/setup)。

GUI 打开的 Codex、Claude 或登录工具结束后，会显示退出码并留在同一容器的交互 Shell。更新完成后输入 `codex` 或 `claude` 启动新版本；输入 `exit` 关闭该终端。不会自动重跑 AI 命令。Linux 终端本身正常退出仍关闭该会话；非交互 CLI 保留工具退出码，不额外停留。自定义 Windows 终端仍使用通用配置，没有为特定第三方终端增加专属分支。

## 数据、隔离与失败处理

更新数据存于当前身份已有的 tools-home 卷；独立 Profile 的版本与账号一样隔离。同一共享身份内的项目共用该身份的工具版本。停止环境、重新打开项目或迁移宿主数据目录，不清除这份用户安装。

网络中断、代理异常、TLS 错误或磁盘/权限不足会保留错误，现有网络停止规则不变；不会切换直连或提高权限。更新后版本与路径以 `codex --version`、`claude --version`、`command -v codex`、`command -v claude` 的实际输出为准，不能只根据安装提示判断成功。第三方更新器的原子更新/回滚能力由其实现决定，不承诺每种中途失败均可自动回滚。

镜像中的系统版本仍在，不会因为前缀设置而被覆盖。通常优先使用可执行的用户安装；没有可用的用户入口时继续按 PATH 查找镜像版本。软件不自动删除或修复损坏的用户安装。需要回退时先停止工具，再检查对应工具的安装状态，仅处理已确认属于它的用户安装，保留账号与配置。回滚 ENGE SPX 版本不会删除用户安装，但旧版不保证优先解析该目录。
