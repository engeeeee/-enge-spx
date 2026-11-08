<p align="center"><img src="assets/logo.svg" width="88" alt="ENGE SPX"></p>
<h1 align="center">ENGE SPX</h1>
<p align="center">自己的项目，独立的工作环境，可核对的代理出口。</p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>

ENGE SPX 是 [engeeeee](https://github.com/engeeeee) 维护的个人项目，为 Windows 上的 Claude Code、Codex 和共享 Chromium 提供 Linux 容器工作环境。支持软件内固定“加密线路 → 落地代理 → 目标服务”，也可兼容本机 v2ray 代理。线路出口和落地出口分别核对。

当前版本：**0.5.1 Preview**。支持 Windows x64，需要 Docker Desktop 的 Linux containers / WSL 2 后端，Docker Engine 28 或更新版本。软件不接管系统代理。

![ENGE SPX 工作台](docs/images/spx-overview.png)

界面截图来自源码图形测试环境；[查看品牌、界面和命名说明](docs/branding.zh-CN.md)。

## 下载安装

打开 [Releases](https://github.com/engeeeee/-enge-spx/releases/tag/v0.5.1-windows)：

- **安装版**：`ENGE-SPX-Windows-x64-0.5.1-Setup.exe`。当前用户安装，提供开始菜单和桌面快捷方式。
- **免安装版**：`ENGE-SPX-Windows-x64-0.5.1-Portable.zip`。完整解压，运行根目录 `ENGE-SPX.exe`；保留 `_internal` 文件夹。

两个版本都不需要另外安装 Python。命令行入口为 `spx.exe`。程序尚未代码签名。

先安装并启动 [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)。打开 ENGE SPX，在“下载与安装”获取运行环境。下载支持暂停、续传、速度与剩余时间显示，完成后校验 SHA-256，再导入 Docker。预构建包同时支持 classic 和 containerd 镜像存储，不覆盖已有镜像标签。

## Pebrel 和 D 盘设置

在“偏好设置 → 工作区终端”选择 **Pebrel**，点击“检测终端”或手动选择 `pebrel.exe`，测试后保存。此后 Claude Code、Codex、Linux 终端和登录窗口都使用这个设置。自动选择会优先寻找 Pebrel，其次是 Windows Terminal、PowerShell 7、Windows PowerShell。也可选择“自定义程序”填写其他终端的 exe 和启动参数。命令行 `spx claude` 继续使用当前终端。

在“偏好设置 → 应用数据与下载缓存”选择专用空目录，例如 `D:\ENGE-SPX\data`，点击“检查并迁移应用数据”。软件会停止工作区，复制并校验配置、日志及已下载或部分下载的运行环境文件，然后切换默认位置、清理原目录的已校验副本。已有安装标识和 Docker 资源会保留，之后的新下载也进入新目录。

Docker 镜像、容器和账号数据卷在 Docker 自己的数据盘中，需要使用下方的“Docker 数据盘迁移助手”另行迁移。例如选择 `D:\DockerData`，点击“准备迁移”，在 Docker Desktop 的 **Settings → Resources → Advanced → Disk image location** 选择同一目录并 **Apply**。等待 Docker 恢复运行，返回软件点击“核验迁移结果”，再检查并确认连接。这里需要在 Docker 确认一次；软件不会直接搬动正在使用的 VHDX 文件。

两项迁移可以独立执行；完成应用数据迁移不会自动移动 Docker 数据盘。项目原文件夹与程序安装目录也各自保留。详细步骤、失败恢复和参数例子见 [存储与终端设置](docs/storage-terminal.zh-CN.md)。

## 线路保护与落地代理

```text
Claude Code / Codex / Chromium → 固定加密线路 → 落地代理 → 目标服务
```

1. 在“连接与代理”添加远程 SOCKS5、HTTP 或 HTTPS 落地。通过“批量导入”追加线路节点不会删除已有落地。
2. 从 v2ray 复制受支持的线路分享链接并导入。在“前置线路保护”启用线路，选择“软件内双跳（推荐）”，再选择导入的加密线路节点；线路和落地分别选择。
3. 线路服务器地址为域名时，填写服务商提供的服务器 IPv4。软件保留原 TLS 名称和证书校验，不通过本机 DNS 查询线路或落地。
4. 保存并检查连接，分别核对线路出口、落地出口、预计地区与时区，再确认启用。可填写已知的线路出口 IPv4，在首次检查前就限制出口。
5. 选择项目，打开 Claude Code、Codex 或 Linux 终端。需要授权时，在共享 Chromium 的远程画面内完成登录。

软件内双跳直接控制固定的线路出站，不包含直连或自动回退出口。线路失效时连接失败；确认后的线路出口或落地出口变化被检测后停止环境。IP 变化检测有周期和超时；它不能替代对线路服务商的信任，也不提供匿名保证。

如果继续使用现有 v2ray 客户端，在模式中选择“本机代理（v2ray 兼容）”，填写实际回环监听地址或读取系统代理。可导出 v2rayN 路由规则并在客户端置顶。兼容模式会锁定线路检查测得的出口，但不能证明外部客户端对每个目标都未使用 DIRECT，特别是首次检查已被错误分流时。详见 [v2ray 线路保护与检测边界](docs/line-protection.zh-CN.md)。

勾选“下载运行环境时使用本机代理”后，下载和订阅使用配置的本机下载代理或系统回环代理；找不到代理会停止，不自动改为直连。主动取消勾选才直接下载。下载不经过工作区的双跳链路，源码构建使用 Docker Desktop 自己的网络和代理配置。

## 导入格式

支持单条或多条代理 URI、JSON、Clash `proxies`、Base64 列表及本地配置文件：

```text
socks5://user:password@proxy.example:1080#我的落地
http://user:password@proxy.example:8080
https://user:password@proxy.example:443
```

无认证时省略 `user:password@`，特殊字符使用 URL 百分号编码。HTTPS 代理表示与代理建立 TLS 连接，必须通过证书验证；HTTP 代理同样可用 CONNECT 访问 HTTPS 网站。

导入窗口区分“代理链接 / JSON / Clash”和“订阅地址（HTTPS）”，避免把 HTTPS 代理当成订阅。订阅仅主动获取，不保存其地址，不自动刷新。

还支持 Trojan TCP/TLS、VLESS TCP/TLS、VMess AEAD TCP（可选 TLS）、Shadowsocks AEAD / 2022 TCP。暂不支持 WS、gRPC、Reality、XTLS、插件、uTLS、自定义证书、跳过 TLS 校验或 SOCKS5 外加 TLS；不支持的条目会明确拒绝，不会剥掉参数后继续连接。软件内线路要求加密，普通 HTTP/SOCKS5 可作为落地。当前仅支持 IPv4 出口；启用线路后落地域名由线路解析，未启用线路时节点地址仍由本机解析。

## 数据和隔离边界

新安装的设置默认位于 `%LOCALAPPDATA%\ENGE-SPX`，迁移后跟随自选目录；`%LOCALAPPDATA%\ENGE-SPX-location.json` 只保留很小的位置记录。程序默认位于 `%LOCALAPPDATA%\Programs\ENGE-SPX`。设置包含代理密码，当前未使用 Windows 凭据库加密；迁移会为目标设置个人访问权限。账号、会话和浏览器资料保存在 Docker 数据卷，项目文件仍在你选择的原目录。

**项目目录可读写共享。** 工具能修改或删除真实项目文件，也能读取其中的密钥和配置。只共享必要目录，正常使用版本管理。未选中的本机目录不主动挂载；工具容器不挂载 Docker 管理接口，浏览器不挂载项目和工具账号卷。

工具与浏览器共用受控网络，工具账号在项目间共享。环境内浏览器资料不自动继承本机浏览器的登录态。Chromium 当前以 `--no-sandbox` 运行，关闭了浏览器自身沙箱；容器隔离仍在，但这不是运行任意不可信程序的安全保证，也不保证匿名或服务商接受账号。

关闭窗口后，已确认环境与监测进程继续运行。结束工作请点“停止环境”或执行 `spx stop`。停止和卸载不会主动删除项目或 Docker 数据卷。备份需要同时保留项目、私有目录和 Docker 数据。

## 从旧版升级

升级前停止环境，退出旧窗口。若新数据目录尚未初始化，程序会自动识别旧版的默认数据目录并继续使用；不移动、删除或另行复制密码文件。旧容器归属、镜像 ID、项目可写层和账号卷保留。首次检查会等待旧版后台监测退出，然后由 ENGE SPX 接管，最长约 40 秒。

升级兼容代码保留了部分旧协议和目录标识；新安装使用 SPX 的命名。已建立环境的时区固定，另一时区请使用独立 `--data` 目录。具体范围见 [升级说明](docs/migration.zh-CN.md)。

## 命令行和源码

```powershell
.\spx.exe doctor
.\spx.exe install
.\spx.exe import-node C:\Private\nodes.txt
.\spx.exe check
.\spx.exe confirm
.\spx.exe --project C:\Projects\MyProject claude
.\spx.exe --project C:\Projects\MyProject codex exec "分析这个项目"
.\spx.exe browser
.\spx.exe stop
```

源码需要 Python 3.12+，包含 Tcl/Tk。双击根目录 `Start-Windows.cmd`；CLI 使用 `spx.cmd`。也可执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\spx.exe
```

`install --from-source` 可从配方构建容器，日志位于数据目录 `build.log`；ARM64 容器可用源码方式，预构建下载包目前仅提供 Linux amd64。

在 x64 Windows 安装 Inno Setup 6，运行 `packaging/windows/Build-Windows.ps1`，安装版、免安装版和校验文件输出到 `dist`。开发结构和验证命令见 [开发说明](docs/development.md)。

安装或下载失败时，参见 [运行环境安装问题](docs/installation-troubleshooting.zh-CN.md)。

## 项目与许可

ENGE SPX 由 engeeeee 独立维护，使用自己的品牌和图标。项目延续此前为该账号开发的 Windows 实现；设计参考和历史来源见 [NOTICE.md](NOTICE.md)，第三方组件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。这不表示所有依赖均由本项目作者编写。

项目沿用 [PolyForm Noncommercial 1.0.0](LICENSE)，非商业许可；第三方组件保留各自条款。Windows 程序构建、容器功能测试和配置检查不能替代独立安全审计或真实 Windows + Docker Desktop 的完整交互验收。
