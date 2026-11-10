# 第一批 P0：沙箱、凭据、升级和恢复

这些改动属于 P0 安全分支，旧版 0.8.2 安装包及其浏览器、网关镜像不具备本页机制。源码审计和后续批次范围见 [审计与实施方案](security-p0-audit.zh-CN.md)。

## 浏览器沙箱

Chromium 继续以 UID/GID 1000 运行，启用 user namespace、PID namespace、network namespace 和 Seccomp-BPF 沙箱。启动前实际读取 `chrome://sandbox`，启动后验证当前窗口 renderer 的 `/proc` 证据：非 root、无 capabilities、`NoNewPrivs=1`、额外 seccomp filter、嵌套 PID namespace。不能取得完整证据时不开放浏览器控制入口。

浏览器容器保持 `--cap-drop ALL`、`no-new-privileges`，增加只读根文件系统，临时文件使用有界 tmpfs。没有 privileged、SYS_ADMIN、unconfined 或关闭 TLS 校验。`--disable-setuid-sandbox` 只排除需要提权的旧式 setuid helper；实际使用的是已验证的 user namespace 沙箱。

浏览器专用 seccomp 从固定版本 [Moby 默认策略](../licenses/Moby-profiles-SOURCE.md)派生。新增允许的调用限于 `clone` 的 NEWUSER/NEWPID/NEWNET 组合、`unshare(CLONE_NEWUSER)` 及沙箱需要的 `chroot`。没有开放 mount、setns 或 bpf。`chroot` 在外层容器仍受已移除的 CAP_SYS_CHROOT 限制；它在 Chromium 创建的无特权 user namespace 中才能成功。其它容器继续使用原 Docker 默认策略。

浏览器与 CLI 的文件系统、PID namespace 和账号卷仍分开。为保留工具的 localhost OAuth 回调，两者继续共用受控网络 namespace。VNC 因此改为浏览器文件系统内的 0600 Unix socket，不再监听 5900 TCP；X11 禁止 TCP 并要求浏览器私有的授权 cookie，以阻止 CLI 利用共享网络 namespace 操作显示。

内核需支持非特权 user namespaces、嵌套 PID/network namespaces、Seccomp-BPF 和 `/proc` 中的 filter / NSpid 证据。Docker Desktop / WSL2 的内核、AppArmor 或其它 LSM 可能拒绝初始化。本软件不修改宿主 sysctl 或全局 LSM 策略，不会静默退回无沙箱。本地管理员需使用实际版本运行验证；Linux CI 成功不能代替 Windows + WSL2 验收。

受限主机可以显式只用 CLI：

```powershell
spx.exe --data D:\ENGE-SPX\data --without-browser --project D:\project claude
spx.exe --data D:\ENGE-SPX\data --without-browser --project D:\project codex
```

此模式不启动任何本机或无沙箱浏览器，工具的自动浏览器登录入口也不可用。需要交互浏览器时，应使用能满足上述条件的受维护 Linux 容器宿主；更强边界可使用专用 VM，但不能用扩大本机容器权限来替代沙箱。

## Windows 凭据保护

仅用标准库 ctypes 调用系统 `CryptProtectData` / `CryptUnprotectData`，当前用户范围、禁止交互 UI；不启用 LOCAL_MACHINE。封套格式为 `enge-spx-dpapi-json`、版本 1。entropy 绑定原安装标识和逻辑文件名，不绑定磁盘路径，因此同账户跨盘迁移继续可读。JSON 对调用方仍保持原有结构、节点 ID 和选择项。

保护的应用文件为 `nodes.json`、`settings.json`、`runtime.json`、`relay.json`、`gateway/config.json` 及旧的 `browser-token.json`。Windows 首次前台入口会迁移旧明文；旧环境应先停止，避免被旧进程重新写入明文。迁移先检查所有源数据和私有目录权限，再预加密、逐项解密核对、原子替换，最后记录完成标记。写入中断后可以继续；解密失败不当作空配置，完成迁移后不接受明文格式的静默降级。不生成明文备份。

网关配置通过 Docker exec stdin 送入容器 tmpfs，读取后立即删除交接文件，sing-box 使用封印后的匿名 memfd。宿主只挂载非敏感租约文件。浏览器授权也通过 stdin / RAM 文件交接后删除。Docker 配置和创建命令没有代理密码或浏览器授权令牌。

CLI 进程确有需要的内部浏览器令牌，通过 Docker exec 的变量名传递，值只放在该 Docker 子进程环境中。第三方终端只接收公共 `spx attach` 命令，不接收令牌环境。Docker 管理端仍可观察必要的运行时凭据；这不是对管理端加密的协议。

本机 noVNC 链接仍携带显示会话的授权能力，系统浏览器需要它建立显示连接；不要分享完整链接，停止或重新检查环境后它会失效。保留旧项目可写层时，旧容器创建元数据可能保留先前已失效的浏览器令牌；新的有效令牌只在需要的 exec 中传入。不会为了清除失效元数据而丢弃项目可写层。

应用的 Docker 错误、构建日志和 GUI 消息进行脱敏；stdin 交接失败不记录原始 stderr。sing-box 原始 stdout/stderr 不保存，避免上游解析错误回显配置；此阶段保留通用退出错误和独立的连接诊断，详细后端结构化错误定位在下一批处理。交互式 Claude / Codex / shell 的输出由工具决定，不由应用改写。

## 升级步骤和失败处理

1. 在旧版停止环境并退出旧 GUI，备份原私有目录、Docker 数据及实际项目。备份可能包含明文，应单独妥善保管。
2. 完整解压或安装新包，以原 Windows 账户启动，继续使用原 `--data` 目录。打开 GUI 不会自动启动 Docker。
3. 凭据保护成功后重新准备运行环境。网关和浏览器需要新镜像；旧网关和无沙箱浏览器不会冒充兼容镜像。工作镜像配方不变，项目容器的可写层、账号卷及浏览器资料卷保留。
4. 重新检查并确认两级出口，再打开工具与浏览器。

若旧的明文配置仍标记为 checking/review/ready，前台入口会拒绝开始迁移，保留原文件并提示先停止；避免旧后台进程把新密文覆盖成明文。已完成保护的新环境可以正常运行并重新打开 GUI，不会因此停止环境。

命令行可查看或显式迁移：

```powershell
spx.exe --data D:\ENGE-SPX\data credentials status
spx.exe --data D:\ENGE-SPX\data credentials migrate
```

权限不足：保留原目录，检查磁盘和当前账户权限，再重新运行迁移；不要删除 instance.json、完成标记或手动重写敏感 JSON。部分替换成功时，新程序能读取已有密文和未替换的旧文件，并继续迁移。

无法解密：使用原 Windows 账户及其 DPAPI 密钥恢复。复制数据到另一台机器、重建账户或丢失系统密钥，可能无法解密；仅复制应用目录不能保证跨机器恢复。不要反复初始化覆盖数据。跨盘搬迁应使用现有迁移功能，以保留安装标识和私有 ACL。

即使敏感配置损坏，仍可用 `spx.exe --data ... stop` 按非敏感的本机 Docker context 与实例归属停止资源；停止路径继续尝试撤销租约，不依赖成功解密节点。它不会启动 Docker Desktop、操作远程 Docker 或删除账号卷。

## 删除和显式回滚

界面的“删除所选代理”先停止环境，再删除节点及派生配置；删除用作线路的节点会清除该线路引用。需要清空所有代理时：

```powershell
spx.exe --data D:\ENGE-SPX\data credentials clear-proxies
```

此命令清空代理节点和前置配置，删除网关配置、显示描述与旧令牌文件的应用持久化引用，保留项目和工具账号卷。不承诺清除系统备份、SSD 历史块或操作系统内存中的所有副本。

旧版不能读取新封套。确需回滚时，在仍能解密的原账户下停止环境，由新版本显式导出旧 JSON 到新的私有目录：

```powershell
spx.exe --data D:\ENGE-SPX\data credentials export-legacy --output D:\SPX-private-rollback --allow-plaintext
```

导出**含明文凭据**；此标志是明确选择，不是迁移失败后的自动回退。导出不把源节点和设置降级为明文，不复制日志、缓存或运行中的令牌；执行前会停止环境并更新运行状态。旧程序指向导出目录后，需重新准备其匹配的旧网关与浏览器镜像，并重新确认出口。导出目录与原目录共用实例标识及 Docker 卷，禁止同时运行。浏览器 Chromium 版本变化可能影响 Profile 向旧版回退，需保留升级前 Docker 备份。验证完成后删除不再需要的明文导出。

## 保护范围

没有新增 Python 包或加密依赖。Moby 策略使用 Apache-2.0，原文、固定来源与修改说明已纳入 licenses 和第三方声明；项目 PolyForm Noncommercial 许可证不变。

DPAPI 不保护同一账户下的恶意代码、宿主管理员或 Docker 管理端。CLI 工具自行保存的 OAuth/API 凭据、Chromium Cookie/Profile 和下载文件仍在各自持久卷中，本批没有声称对这些卷做 DPAPI 加密。Linux 仅使用私有目录/文件权限。多项目仍共享默认工具身份及浏览器 Profile，项目级身份隔离属于第四批。
