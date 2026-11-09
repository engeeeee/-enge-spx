# GitHub 仓库简介

仓库路径为 `engeeeee/ENGE-SPX`，产品显示名称为 **ENGE SPX**。GitHub 的仓库路径不能包含空格，因此两者形式不同。

建议将首页右侧 **About** 设置为以下中文简介，先说明用途，再列核心能力：

> 面向 Windows 的 AI 编程隔离工作台。在 Docker 容器中运行 Claude Code、Codex 和独立浏览器，通过指定的加密线路＋落地代理访问服务；以项目范围挂载、双出口核验和异常停机，减少对本机日常环境的暴露并约束工作区网络路径。

主页和 topics 的可核对配置保存在 [.github/repository.json](../.github/repository.json)。仓库提供 [Sync repository About](../.github/workflows/repository-about.yml) 流程：配置专用密钥后，修改这个 JSON 并推送到 `main` 会自动同步中文简介和主页。没有密钥时会明确失败，不会把 README 更新当成 About 已更新。

## 为同步流程授权

当前托管 GitHub 连接提供仓库文件操作，但不提供 About 设置写操作。调整聊天内的“自动批准”不会增加 GitHub 的仓库管理权限。无需把令牌发送到聊天、写入源码，或给所有仓库授权。

1. 打开 [GitHub 细粒度令牌设置](https://github.com/settings/personal-access-tokens/new)，创建一个用途为 `ENGE SPX About` 的令牌，建议设置较短有效期，例如 7 天。
2. Resource owner 选择 `engeeeee`。Repository access 选择 **Only select repositories**，仅勾选 **ENGE-SPX**。
3. Repository permissions 中只添加 **Administration → Read and write**；Metadata 的必需读取权限由 GitHub 自动附带。修改仓库简介所需权限见 [GitHub 官方接口说明](https://docs.github.com/en/rest/repos/repos#update-a-repository)。该管理权限本身不只涵盖 About；流程代码只发送 `description` 和 `homepage` 两个字段。
4. 生成后打开 [ENGE-SPX 的 Actions Secrets](https://github.com/engeeeee/ENGE-SPX/settings/secrets/actions/new)，创建 Repository secret，名称为 **`SPX_ABOUT_TOKEN`**，Secret 填刚生成的令牌。GitHub 的 [Secrets 使用说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)介绍了该入口。
5. 打开 [同步流程](https://github.com/engeeeee/ENGE-SPX/actions/workflows/repository-about.yml)，选择 **Run workflow → main**；也可重跑之前缺少密钥而失败的任务。

流程读取版本化 JSON，仅对固定的 `engeeeee/ENGE-SPX` 发送简介和主页更新，再以无凭据的公开请求核验结果。令牌只传给该更新步骤，不写入 Git 配置或打印在日志中；它不会同步 topics 或修改可见性、访问控制和默认分支。没有在 fork 或其他分支执行的入口。

成功后可在工作流 Summary 和仓库 About 查看结果。若后续还需自动同步，需在有效期到期前更新 secret；只改这一次时，可以在成功后删除 secret，并在 GitHub 令牌设置中撤销令牌。

## 本地命令行方式

维护者也可在仓库 About 的齿轮中直接粘贴简介，或在已授权 GitHub CLI 的机器上执行：

```powershell
.\tools\Update-Repository.ps1 -WhatIf
.\tools\Update-Repository.ps1
```

脚本只同步该 JSON 中的 description、homepage 并补充 topics，不修改访问控制、默认分支或既有 topics。`-WhatIf` 只做本地检查，不需要 GitHub CLI 或网络。实际执行需要当前 GitHub 身份具有修改此仓库设置的权限。

GitHub 的仓库文件操作与 About 设置是不同能力。如果使用的连接只支持代码、Issues 和 Releases，应明确说明尚未应用 About，不能用 README 修改冒充设置已更新。
