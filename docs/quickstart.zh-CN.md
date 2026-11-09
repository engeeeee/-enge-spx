# 从安装到第一个工作区

ENGE SPX 把 AI 编程工具和浏览器放进 Linux 容器，通过你选择的代理访问目标服务。Windows 桌面程序负责配置、核验和启动。它不会替你购买线路、落地代理或 AI 服务账号。

## 1. 安装一次 Docker Desktop

需要 Windows x64，以及能运行 Linux containers 的 Docker Desktop；使用 WSL 2 后端，Docker Engine 28 或更新版本。先按 [Docker 官方 Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)完成安装。首次安装涉及的许可、虚拟化、WSL 更新或重启，需要你在 Docker / Windows 中完成。

安装版和免安装版 ENGE SPX 都不需要额外安装 Python。在 [Releases](https://github.com/engeeeee/ENGE-SPX/releases)选择同一版本的 `Setup.exe` 或 `Portable.zip`。便携版必须完整解压，保留 `_internal`，再运行 `ENGE-SPX.exe`。程序目前未代码签名。

## 2. 一键准备

打开 ENGE SPX，点击总览页的 **一键准备环境**：

1. 已安装但未运行的 Docker Desktop 会自动启动；程序等待 Linux 引擎实际可用。
2. 已有匹配的运行环境会复用；缺失时下载、校验并导入。
3. 没有节点时进入代理配置；已有节点时继续检查连接。
4. 核对出口后，由你明确确认启用。

总览页显示当前步骤，可点击“取消准备”。取消会停止后续操作，保留下载和已有数据；已经启动的 Docker Desktop 会继续运行。等待引擎超时约为三分钟，不包含后续下载和连接检查时间。软件不会自动安装 WSL、接受 Docker 许可、切换引擎或修改默认 Docker 上下文。

打开软件只检测 Docker 状态，不启动 Docker 或容器，也不下载运行环境。
点击“一键准备环境”或 **下载与安装 → 启动并检测** 后才会启动 Docker。
旧版保存的自动启动选项不再生效；你可以先修改代理、终端或数据位置，再决定何时准备环境。

## 3. 设置下载代理

如本机使用 v2ray，可在一键准备卡片填入它的实际 HTTP / SOCKS 回环监听地址，例如 `http://127.0.0.1:10809`，也可读取系统代理。端口以你自己的客户端为准。

勾选代理下载时，找不到代理就停止，不会偷偷切换直连。需要直连下载时，请主动取消该选项。下载代理只负责运行环境和订阅，独立于之后的工作区双跳配置；源码构建的镜像拉取使用 Docker Desktop 自己的网络。

下载支持暂停和断点续传，导入前核对 SHA-256、文件大小和镜像配方。无需手工下载 Releases 中的 runtime 归档。

## 4. 选择线路和落地

推荐在 **连接与代理** 中分别选择：

- **落地**：远程 SOCKS5 / HTTP / HTTPS 代理，按需填写认证。
- **前置线路**：导入受支持的加密线路分享链接，启用“软件内双跳”，线路与落地分别选择。

线路服务器使用域名时，需要填写服务器 IPv4，原 TLS 名称与证书校验保留。支持的协议和导入例子见 [代理配置](proxies.zh-CN.md)。如果继续使用外部 v2ray 客户端，选择“本机代理（v2ray 兼容）”；它的目标分流规则仍由外部客户端决定，见 [线路保护](line-protection.zh-CN.md)。

点击 **一键启动并检查**，核对线路出口、落地出口和时区，再确认启用。检测失败时先检查错误原因，不要接受不认识的出口。软件内双跳没有直连备用出口；已确认的出口发生变化，被监测到后会停止环境。

## 5. 打开项目和工具

选择项目目录，打开 Claude Code、Codex 或 Linux 终端。需要浏览器授权时，通过共享 Chromium 的远程画面完成登录；其资料与本机浏览器分开保存。命令实际运行在 Linux 容器，窗口由 Windows 的终端程序承载。

项目目录是 **读写共享** 的，AI 工具仍能修改、删除项目文件和读取项目内密钥。只选择必要目录，并保留版本管理和备份。完整边界见 [隔离与安全模型](security-model.zh-CN.md)。

## 可选：使用 Pebrel、迁移到 D 盘

在偏好设置选择 Pebrel，自动检测或指定 exe，测试后保存。自定义终端支持程序路径和启动参数模板。

应用数据与下载缓存可迁移到例如 `D:\ENGE-SPX\data`；Docker 镜像、容器和数据卷需通过独立的 Docker 数据盘迁移助手，在 Docker Desktop 的 Disk image location 中应用变更。两项迁移不是同一件事，详见 [存储与终端设置](storage-terminal.zh-CN.md)。

## 遇到问题

| 提示 | 下一步 |
| --- | --- |
| 未找到 Docker | 使用界面的官方安装入口，完成安装后重试 |
| 等待 Linux 引擎超时 | 打开 Docker 窗口，检查许可、WSL 2、初始化和 Linux containers 状态 |
| 上下文不可用 | 在偏好设置核对本机上下文名称；Desktop 通常为 `desktop-linux` |
| Docker 当前不是 Linux containers | 在 Docker Desktop 手动切换，软件不会更改你的其他环境 |
| 需要 Engine 28+ | 更新 Docker Desktop 后重新检测 |
| 下载代理不可用 | 核对 v2ray 是否运行、回环端口和认证；或明确选择直连下载 |
| `docker-credential-desktop` 未找到 | 新版会补齐子进程工具路径；仍失败时按 [安装排障](installation-troubleshooting.zh-CN.md)检查 Docker 安装 |

总览页“复制诊断信息”仅包含版本、系统、Docker 状态和错误代码等摘要，不包含节点、密码、出口 IP 或项目路径。提交问题前仍应自行检查附加日志和截图，详见 [支持指南](../SUPPORT.md)。

关闭主窗口不会停止已确认的环境。结束工作请点击 **停止环境**，或执行 `spx stop`；软件不会关闭整个 Docker Desktop 或其他项目的容器。
