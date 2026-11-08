# 0.3.1 安装修复验证

日期：2026-11-08。应用代码提交：`570dc74bd20169268f7dfd4f47a57ba118dab1c8`。

- [修复版下载](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.3.1-windows)
- [完整成功构建](https://github.com/engeeeee/ENGE-SPX/actions/runs/42456082216)
- [安装问题排查](installation-troubleshooting.zh-CN.md)

用户提供的源码构建日志显示，Docker 找到了 CLI，却无法通过 PATH 找到
`docker-credential-desktop`。0.3.1 为 Windows Docker 子进程补齐 CLI 所在目录
及可用的 Desktop 工具目录，保留 Docker 配置路径、凭据存储与父进程环境。
Linux 上维持原来的 PATH，不增加 Windows 路径处理。

Windows CI 在初始 PATH 不包含助手目录时，用系统原生文件查找程序确认修复后
可找到同目录的凭据助手。另有大小写、带空格路径、分离安装目录、Docker 配置
保留及父环境不变的回归检查。这项检查验证查找行为，没有使用用户的 Docker
登录凭据或在真实用户的 Docker Desktop 上执行身份认证。

下载方面新增系统回环代理识别、实际线路显示、超时和 HTTP 状态区分，以及
错误信息不泄露认证和签名 URL 的检查。用户未提供原始预构建下载错误，不能
因此确认它与凭据助手问题具有同一根因。

代理链集成发现的启动就绪问题也已处理：确认网关内的转发监听实际可连接后，
才测量出口，不再依赖固定的短暂等待。

最终 Windows / Linux 各执行 59 项检查，各有一项依平台条件跳过，其余通过。
Windows x64 GUI / CLI 自检、启动、安装卸载，以及原生 Linux x64 的工具和浏览器、
HTTP 前置到 SOCKS5 / HTTP 落地、线路失效阻断均通过。完整预构建包在 containerd
和独立 classic 存储中均完成实际下载、摘要校验、导入、重复安装和数据保留检查。

已下载最终 Windows 构建 Artifact，核对摘要及两份包的 SHA-256，确认 GUI / CLI
为 PE x64、Windows 产品版本为 0.3.1。发布后使用应用的 HTTPS 客户端读取了公开
清单，核对配方和镜像标识，并验证了公开下载地址及校验文件。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| ENGE-SPX-Windows-x64-0.3.1-Setup.exe | 15,357,292 | `de57aa2d3ec0d4cc54b6411aab0be3d049f693e56b799c0bac288c1f4beb0078` |
| ENGE-SPX-Windows-x64-0.3.1-Portable.zip | 21,397,947 | `d5601f55fe04215b932b23f3cd47f69a8ac219057df857810dd636128cfabcb8` |
| ENGE-SPX-Runtime-linux-amd64-0.3.1.tar.gz | 949,401,770 | `54e2654d7be441d16873e1f212daebdead29bafa830256d85f85ba4631e45568` |

容器配方与 0.3.0 保持一致，已安装且匹配的镜像可继续使用。其他预览限制仍然
适用，包括尚未完成真实 Windows 桌面全流程交互验收、无代码签名、Chromium
关闭自身沙箱、项目读写共享和工具账号共享。
