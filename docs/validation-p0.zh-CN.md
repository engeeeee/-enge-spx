# 0.8.3 P0 安全改造交付与验证

日期：2026-11-10。审计起点为 `c08beb1f3224150d95dbc1c5fb05e1283ff9c5ff`（0.8.2）。
工作分支为 `security/p0-hardening`，[PR #1](https://github.com/engeeeee/ENGE-SPX/pull/1)。本记录不是独立第三方审计，也不代表已经发布正式安装包。

## 1. 修改概述

第一批只推进 Chromium 沙箱及代理凭据保护，并修复审查中发现的 VNC/X11 访问边界。Python 3.12+、PySide6、Docker Desktop/WSL2、既有 sing-box、固定链路、双出口、异常停机和用户数据持久化机制保留。

已经存在的按需 GUI 页面、手动启动 Docker、锁竞争等待、会话复用、续租日志和转发背压没有重新实现。协议后端适配、QUIC/UDP、资源预算和多 Profile 仍按后续批次推进。完整模块图、问题定位、风险和复杂度见 [源码审计](security-p0-audit.zh-CN.md)。

## 2. 涉及文件

以下路径相对 `src/enge_spx/`，工程文件除外；完整差异见 PR 的 Files changed。

| 目的 | 源代码 / 资源 |
| --- | --- |
| DPAPI 与兼容迁移 | `credentials.py`、`state.py` |
| 生命周期、最小凭据交接和终端接入 | `engine.py`、`__main__.py`、`invocation.py`、`relay.py` |
| 错误与日志脱敏、代理删除入口 | `redaction.py`、`ui/controller.py`、`ui/window.py` |
| 浏览器权限和实际 renderer 核验 | `browser_security.py`、`resources/containers/browser.py`、`sandbox_status.py`、`browser-seccomp.json`、`Dockerfile.browser` |
| RAM 配置与显示隔离 | `resources/containers/runtime_secret.py`、`gateway.py`、`Dockerfile.gateway`、`vnc_stdio.py` |
| 自动化验证 | `tests/test_credentials.py`、`test_security_p0.py`；更新 `test_workspace_launch.py`、`test_line_security.py`、`test_migration.py`、`integration_runtime.py` |
| 可重跑工具 | `tools/probe_sandbox.py`、`benchmark_p0.py`、`check_frozen_credentials.py` |
| CI 和打包 | `.github/workflows/security-p0.yml`、`ci.yml`；Windows 版本元数据与 Installer；`__init__.py` |
| 文档与许可 | README 中英文、SECURITY、CHANGELOG、开发/迁移/安全模型、本文与 P0 升级文档；Moby Apache-2.0 原文及固定来源、THIRD_PARTY_NOTICES |

没有改动工作镜像的 Dockerfile 或 CLI 安装配方，现有项目可写层、工具账号卷和浏览器 Profile 卷保留。网关与浏览器必须更换新镜像，旧的不安全镜像不会被接受为兼容运行时。

## 3. 核心方案

Chromium 使用非 root user namespace 沙箱及 Seccomp-BPF。固定 Moby 默认 allowlist 只补已验证需要的 clone namespace 组合、`unshare(CLONE_NEWUSER)` 和 namespace 内 `chroot`；不启用 privileged、SYS_ADMIN 或 unconfined。外层保持移除全部 capabilities、no-new-privileges，浏览器根文件系统只读。

启动先读取 Chromium 的沙箱页面，再核对实际窗口 renderer 的 `/proc` 证据。检测器同时支持普通 argv 与 Chromium 的 Linux 进程标题改写，要求准确匹配 renderer 类型及父子关系；不会因检测不便而放宽内核条件。沙箱或显示初始化失败时拒绝开放浏览器控制入口，无无沙箱重试。

为保留 localhost OAuth 回调，CLI 与浏览器继续共用受控网络 namespace，文件系统/PID/账号卷继续分开。VNC 改为浏览器私有 0600 Unix socket；X11 不监听 TCP，abstract socket 需要私有 cookie，CLI 不能未经授权操作显示。

Windows 应用敏感 JSON 使用当前用户 DPAPI、版本 1 封套及与实例/逻辑文件名绑定的 entropy，路径不参与绑定。旧数据预加密并逐项核对后原子替换；加密、ACL、写入、解密或版本错误不清空配置、不回退明文。旧环境仍活动时拒绝开始明文迁移，以免旧写入者破坏封套；内部子进程不重复申请父进程的迁移锁。

网关和浏览器使用 stdin/RAM 交接；只挂载非敏感租约。sing-box 的 JSON 保存在 sealed memfd，交接文件读取后删除。第三方终端只得到公共 attach 命令，必要的 CLI 浏览器令牌仅通过 Docker exec 的变量名/子进程环境传入。删除代理会停止环境并清理派生引用；显式旧格式导出支持回滚，源节点和设置继续加密。

无需新增 Python 依赖或加密库。新增策略是固定来源的文本资源，保留 Apache-2.0 义务；项目 PolyForm Noncommercial 许可不变。详细升级和回滚步骤见 [P0 使用说明](security-hardening.zh-CN.md)。

## 4. 已实现功能与证据

- Chromium 报告的 namespace、PID/network namespace、Seccomp-BPF 均为 Yes；实际 renderer 取得非 root、NoNewPrivs、零 CapEff、额外 filter 和嵌套 PID namespace 证据。
- 容器未增加 capabilities、设备或宿主 PID/IPC namespace；浏览器拒绝非预期 bind mount；没有新增宿主发布端口。
- VNC 重连、坏令牌/外部 Origin 拒绝、CLI 对 VNC TCP/X11 TCP/未经授权 abstract X11 的访问阻断通过。
- 真实 Chromium 执行受控本地登录页面；Cookie 和 Local Storage 在停止、更换浏览器容器后保留；浏览器可访问 CLI 的 localhost OAuth 回调。没有使用真实云服务账号。
- 实际网关只挂租约；Docker 创建配置/argv 中无所选代理密码和浏览器令牌；RAM 交接文件已删除，memfd seals 经实际检查。
- Windows 原生 DPAPI 和冻结后的 spx.exe 均完成迁移、显式回滚及代理删除；节点 ID/选择项保留，密文损坏、用途绑定、写入/ACL 失败及中断恢复有覆盖。
- 0.8.2 的双来源出口、固定双跳、第一跳失败不回落地、异常停机、190 秒无 shell 输入续期、中文 PTY、字体清单、项目可写层、账户卷和跨盘迁移回归通过。

## 5. 测试命令和实际结果

成功的完整冻结验证为提交 `48760c44499ba4d01865f77d371dd62816526916`，见 [P0 CI 42764782761](https://github.com/engeeeee/ENGE-SPX/actions/runs/42764782761)。它的 Windows/Linux、沙箱探针、Windows 打包与 Docker 集成所有 job 均 success。

| 命令 / 检查 | 冻结验证的实际结果 |
| --- | --- |
| `python tools/check_repository.py` | 通过，33 个文档和版本/仓库元数据核对 |
| `python -m unittest discover -s tests -v`，`PYTHONPATH=src` | Python 3.12：Windows 169 项，4 项平台跳过；Linux 169 项，8 项平台跳过，无失败 |
| `python tools/probe_sandbox.py --output sandbox.json` | Docker 默认策略拒绝所需 user namespace；受限策略成功；实际窗口 renderer 的全部内核条件通过 |
| `python -u tests/integration_runtime.py --context default --output integration.json` | 沙箱、显示、Cookie/Local Storage、RAM/seals、190 秒续期、故障关闭、持久化和迁盘通过 |
| `python -u tests/integration_chain.py --context default` | 本机 HTTP 线路接 SOCKS/HTTP 落地、软件内加密链路、远端域名解析和第一跳中断检查通过 |
| `python tools/export_runtime.py ...` 与 `python tests/integration_prebuilt.py ...` | 原生 containerd 和独立 classic overlay2 镜像存储均导入并重复核验通过 |
| `packaging/windows/Build-Windows.ps1` | Python 3.12 x64 GUI/CLI、安装包、便携 ZIP 和 SHA-256 构建通过 |
| `spx.exe --self-test`、`python tools/check_frozen_credentials.py dist/ENGE-SPX/spx.exe` | 真实 DPAPI、沙箱资源、冻结 CLI 迁移/回滚/删除通过 |
| 原生与冻结 GUI、125%/150%/200% DPI、安装/卸载 | 通过；打开软件不自动启动 Docker，卸载不删除用户数据 |

冻结验证后又补充“活动旧环境拒绝迁移”和编码凭据脱敏回归。最新代码的总项数为 171；当前 PR 最新 head 的 CI 结果优先于冻结快照。Linux ARM64 / Python 3.14 的本地重复检查通过，仅作为额外回归，不能替代上述 Python 3.12/Windows 验证。

复现需要源代码依赖和相应 Docker/Windows 环境；集成会构建镜像、访问注明的出口服务，仅删除临时实例所属资源。它不是在用户真实 Docker Desktop/WSL2、v2rayN 或 Pebrel 上做的全流程验收。

## 6. 修改前后性能

固定 0.8.2 起点与冻结验证 `48760c4`，每一对在同一 runner 内顺序执行。原始数据保存在 [Windows 应用数据](evidence/p0-host-48760c4.json)与 [Docker 浏览器数据](evidence/p0-docker-48760c4.json)，含具体版本和证据来源。未设置预期改善比例。

Windows Server 2025 / Python 3.12.10：20 个合成节点，写入 15 次、读取 100 次、Engine 构建 15 次取中位数；GUI 空闲采样约 5 秒，只计该 Python 进程。

| 指标 | 0.8.2 | P0 | 含义 |
| --- | ---: | ---: | --- |
| 写入 20 节点 | 6.953 ms | 10.073 ms | 含原子持久化及新增 DPAPI 开销 |
| 读取 20 节点 | 0.177 ms | 0.988 ms | 新增封套/路径验证及解密 |
| Engine 构建 | 6.293 ms | 9.501 ms | 含资源和受保护状态读取 |
| GUI 工作集 | 112.95 MiB | 115.41 MiB | 单进程，不含 Docker/WSL |
| 应用持久文件 | 6,864 B | 7,263 B | 合成配置，不含镜像、工具账号或 Profile |
| GUI 空闲 CPU / 单核 | 0.3106% | 低于该次采样量化阈值 | 短窗口和 Windows CPU 时钟量化，不表示零开销或省 CPU |
| Qt 导入到首帧 | 2,963.950 ms | 778.596 ms | 单次顺序测量受缓存/杀软/调度影响，不作提速结论 |

Linux x64 / Docker 29.4.2 / Python 3.12.16：每个版本 3 次新浏览器容器，新 Profile，2 GiB 上限、512 MiB shm、network none，无 noVNC 客户端；就绪后等待 5 秒，每次 3 份 Docker stats。旧版默认 about:blank，新版为触发 renderer 核验的本地文档，不能外推到实际网页负载。

| 指标 | 0.8.2 | P0 |
| --- | ---: | ---: |
| 浏览器控制入口就绪，中位数 | 537.059 ms | 2,113.671 ms |
| Docker stats 内存，9 次采样中位数 | 223.3 MiB | 224.6 MiB |
| Docker stats CPU，9 次采样中位数 | 0.03% | 0.25% |
| 进程数，中位数 | 15 | 16 |
| Profile 文件字节，中位数 | 4,664,202 | 4,715,853 |
| 可写层字节，中位数 | 20,480 | 4,096 |
| 停止耗时，中位数 | 459.576 ms | 332.045 ms |
| 停止后容器仍运行 | 3 次均 false | 3 次均 false |

这批增加了沙箱证明的启动成本，未声称整体提速。新容器只在创建/重启时做一次完整初始化证明，已有运行浏览器继续复用；没有减少网络监测。可写层变化不代表 Profile、镜像或 WSL 总磁盘空间减少，停止容器也不保证 WSL 立即归还页缓存。

系统未运行软件时的整机基线、CLI 空闲、真实 Claude/Codex 活动、浏览器实际交互、Docker Desktop/WSL 总量和完全停止后的宿主资源回收，需在第三批通过受控设备持续测量；本批没有伪造这些数据或预测提升百分比。

## 7. 遗留问题与范围

- Windows 原生 CI 验证真实 DPAPI，Linux CI 验证真实 Docker；尚未在用户 Windows/Docker Desktop/WSL2 的实际内核/LSM 组合验收。条件不足时阻止浏览器启动，安全替代是显式 `--without-browser`，不放开全局策略或容器权限。
- 登录测试为实际 Chromium + 本地合成 Cookie/Storage/OAuth 回调，未登录真实 Claude/Codex 账号；不能承诺云服务准入、匿名或不可识别。
- DPAPI 不保护同账户恶意程序、管理员或 Docker 管理者。工具账号和浏览器资料卷仍需私有保存，多项目身份默认共享。Linux 仍是文件权限保护。显示链接携带会话能力，不要分享完整链接。
- 旧 work 容器为保留可写层可能残留已失效的历史令牌元数据；有效令牌只在必要 exec 中传入。显式旧格式回滚会输出明文，用户需妥善保管并清理。
- 当前新包和运行时为 CI 预览工件，未替换公开 Release；发布前一键下载仍指向对应待发布版本，源码构建可用。升级需同时更换新网关和浏览器镜像。
- Reality、WS/gRPC、完整 Hysteria2/QUIC、DNS/UDP/IPv6 故障注入、多 Profile 和资源设置未在本批声称完成。

## 8. 下一批

第二批先抽取 Proxy Backend Adapter，优先复用现有 sing-box 并评估 Mihomo；保持原配置和本机 v2rayN 兼容。逐协议增加参数校验、Reality 公钥/SNI 检查、固定线路/落地生成和实际集成测试。Hysteria2 必须通过完整 QUIC/UDP 路径及 UDP 故障测试，DNS/IPv6/代理中断/证书错误均不得回退 DIRECT。完成这些证据后，再进入资源预算和多 Profile 批次。
