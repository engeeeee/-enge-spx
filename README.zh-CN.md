<p align="center"><img src="assets/logo.svg" width="88" alt="ENGE SPX"></p>
<h1 align="center">ENGE SPX</h1>
<p align="center">自己的项目，独立的工作环境，可核对的代理出口。</p>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>

ENGE SPX 是 [engeeeee](https://github.com/engeeeee) 维护的个人项目，为 Windows 上的 Claude Code、Codex 和共享 Chromium 提供 Linux 容器工作环境。你可以直接使用自己的项目文件，并将流量按“本机线路 → 落地代理 → 目标服务”的顺序转发。

当前版本：**0.3.1 Preview**。支持 Windows x64，需要 Docker Desktop 的 Linux containers / WSL 2 后端，Docker Engine 28 或更新版本。软件不接管系统代理。

![ENGE SPX 工作台](docs/images/spx-overview.png)

界面截图来自源码图形测试环境；[查看品牌、界面和命名说明](docs/branding.zh-CN.md)。

## 下载安装

打开 [Releases](https://github.com/engeeeee/-enge-spx/releases/tag/v0.3.1-windows)：

- **安装版**：`ENGE-SPX-Windows-x64-0.3.1-Setup.exe`。当前用户安装，提供开始菜单和桌面快捷方式。
- **免安装版**：`ENGE-SPX-Windows-x64-0.3.1-Portable.zip`。完整解压，运行根目录 `ENGE-SPX.exe`；保留 `_internal` 文件夹。

两个版本都不需要另外安装 Python。命令行入口为 `spx.exe`。程序尚未代码签名。

先安装并启动 [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)。打开 ENGE SPX，在“下载与安装”获取运行环境。下载支持暂停、续传、速度与剩余时间显示，完成后校验 SHA-256，再导入 Docker。预构建包同时支持 classic 和 containerd 镜像存储，不覆盖已有镜像标签。

## 使用本机线路和落地代理

```text
Claude Code / Codex / Chromium → 本机线路代理 → 落地代理 → 目标服务
```

1. 启动你的线路客户端，确认本机监听地址，例如 `http://127.0.0.1:7890`，无需开放局域网访问。
2. 在“连接与代理”添加远程 SOCKS5、HTTP 或 HTTPS 落地，填入地址、端口及可选的用户名和密码。
3. 开启“通过本机代理连接落地”，填写线路地址；“读取系统代理”只读取设置，不修改系统代理，也不执行 PAC。
4. 保存并检查连接，核对实际落地出口 IP、预计地区与时区，再确认启用。
5. 选择项目，打开 Claude Code、Codex 或 Linux 终端。需要授权时，在共享 Chromium 的远程画面内完成登录。

最终出口由落地提供，能否加速取决于线路质量。线路断开或出口变化被检测后，环境停止，不自动切换为直连。检测存在周期和网络超时。

勾选“下载运行环境时使用本机代理”后，下载优先使用已配置的前置线路；未启用前置线路时，自动读取系统中的回环代理。取消勾选则直接下载。界面会显示实际下载线路，代理密码不显示在日志里。这个选项不设置 Docker 自身拉取镜像的代理；源码构建使用 Docker Desktop 的网络配置。

## 导入格式

支持单条或多条代理 URI、JSON、Clash `proxies`、Base64 列表及本地配置文件：

```text
socks5://user:password@proxy.example:1080#我的落地
http://user:password@proxy.example:8080
https://user:password@proxy.example:443
```

无认证时省略 `user:password@`，特殊字符使用 URL 百分号编码。HTTPS 代理表示与代理建立 TLS 连接，必须通过证书验证；HTTP 代理同样可用 CONNECT 访问 HTTPS 网站。

导入窗口区分“代理链接 / JSON / Clash”和“订阅地址（HTTPS）”，避免把 HTTPS 代理当成订阅。订阅仅主动获取，不保存其地址，不自动刷新。

还支持 Trojan TCP/TLS、VLESS TCP/TLS、VMess AEAD TCP（可选 TLS）、Shadowsocks AEAD / 2022 TCP。暂不支持 WS、gRPC、Reality、XTLS、插件、uTLS、自定义证书、跳过 TLS 校验或 SOCKS5 外加 TLS。当前仅支持 IPv4 出口，节点域名由本机解析；不支持的条目会报告原因。

## 数据和隔离边界

新安装的设置位于 `%LOCALAPPDATA%\ENGE-SPX`，程序位于 `%LOCALAPPDATA%\Programs\ENGE-SPX`。设置包含代理密码，当前未使用 Windows 凭据库加密。账号、会话和浏览器资料保存在 Docker 数据卷，项目文件仍在你选择的原目录。

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
