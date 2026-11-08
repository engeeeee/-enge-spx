# 运行环境安装问题

## 找不到 docker-credential-desktop

报错示例：

```text
error getting credentials: exec: "docker-credential-desktop": executable file not found in %PATH%
```

这表示 Docker 客户端无法通过当前进程的 PATH 找到凭据助手。即使能运行
`docker.exe`，也可能因为启动器继承了安装 Docker 之前的环境而出现此问题。

先退出 ENGE SPX，更新至 0.3.1 或更新版本，再重新尝试。新版为 Docker 子进程
补齐 CLI 所在目录和可用的 Docker Desktop 工具目录，保留原来的 Docker
配置和凭据存储。

如果仍然报同样的错误，在 PowerShell 中检查常见安装位置：

```powershell
Test-Path "$env:ProgramFiles\Docker\Docker\resources\bin\docker-credential-desktop.exe"
Test-Path "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker-credential-desktop.exe"
```

自定义安装位置请以实际目录为准。如果实际 Docker 安装目录内也没有这个文件，
需要通过 Docker Desktop 的安装程序修复工具组件；单纯补齐 PATH 无法恢复缺失
的文件。Docker 的凭据助手要求见 [官方说明](https://docs.docker.com/reference/cli/docker/login/#credential-stores)。

需要暂时继续使用旧版时，可先退出旧窗口，再从同一个 PowerShell 会话启动：

```powershell
$spxDockerBin = "$env:ProgramFiles\Docker\Docker\resources\bin"
$env:Path = "$spxDockerBin;$env:Path"
& "$env:LOCALAPPDATA\Programs\ENGE-SPX\ENGE-SPX.exe"
```

上述路径适用于默认系统级 Docker 和默认 ENGE SPX 安装目录。免安装版或自定义
安装请替换为实际路径。这只改变当前会话及其子进程的环境。

## 无法获取运行环境信息或下载中断

0.3.1 会显示选用的下载线路，并区分连接超时、HTTP 状态错误、代理连接失败
以及清单与程序不匹配。

- 保持线路客户端运行，在“连接与代理”勾选“下载运行环境时使用本机代理”。
  下载优先使用填写的回环地址；未填写时读取系统回环代理。下载代理独立于
  工作区线路开关，首次下载不必先导入线路。
- 初次下载无需先导入落地。系统本机代理可用于下载安装环境，落地在安装后
  再设置和检查。
- 出现 HTTP 404 时确认程序版本与 Release 环境文件版本一致；超时、HTTP
  403 或 429 时检查下载线路或稍后重试。下载中断会保留已完成部分。

0.5.0 起，选择代理下载但未检测到本机回环代理时会停止，不再静默直连。
请在“前置线路保护”的回环代理输入框中填写 v2ray 实际的 HTTP/SOCKS 监听
地址，或读取系统代理。要直接下载，需要主动取消代理下载选项。软件内双跳
控制工作区连接；运行环境和订阅下载使用独立的本机下载代理设置。
- 清单不匹配时保留错误文字和当前程序版本，使用同版本的正式发布文件重试。

运行环境包下载与 Docker 拉取镜像是两条不同流程。源码构建使用 Docker
Desktop 自身的网络和代理配置，软件的下载代理开关只控制预构建环境包。

反馈时注明程序版本、操作步骤，以及下载页或运行日志中的完整错误文字。
节点密码、代理认证和带令牌的订阅链接请删去。
