# GitHub 仓库简介

仓库路径为 `engeeeee/ENGE-SPX`，产品显示名称为 **ENGE SPX**。GitHub 的仓库路径不能包含空格，因此两者形式不同。

建议将首页右侧 **About** 设置为以下中文简介，先说明用途，再列核心能力：

> 面向 Windows 的 AI 编程隔离工作台。在 Docker 容器中运行 Claude Code、Codex 和独立浏览器，通过指定的加密线路＋落地代理访问服务；以项目范围挂载、双出口核验和异常停机，减少对本机日常环境的暴露并约束工作区网络路径。

主页和 topics 的可核对配置保存在 [.github/repository.json](../.github/repository.json)。它是期望配置文件，提交到仓库不会自动修改 GitHub About。维护者可在仓库 About 的齿轮中粘贴简介和主页，也可在已授权 GitHub CLI 的机器上执行：

```powershell
.\tools\Update-Repository.ps1 -WhatIf
.\tools\Update-Repository.ps1
```

脚本只同步该 JSON 中的 description、homepage 并补充 topics，不修改访问控制、默认分支或既有 topics。`-WhatIf` 只做本地检查，不需要 GitHub CLI 或网络。实际执行需要当前 GitHub 身份具有修改此仓库设置的权限。

GitHub 的仓库文件操作与 About 设置是不同能力。如果使用的连接只支持代码、Issues 和 Releases，应明确说明尚未应用 About，不能用 README 修改冒充设置已更新。
