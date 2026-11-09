# 0.8.2 后台续期、转发与字体验证

验证日期：2026-11-09。版本为 **0.8.2 Preview**。

- [Windows 安装版、便携版与校验文件](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.8.2-windows)
- [完整受测构建](https://github.com/engeeeee/ENGE-SPX/actions/runs/42657428237)，所有任务成功。
- 发布标签与受测源码均为 `392636afaf073e16ff06016c010d9512ba67fe02`。
- [Windows 界面与缩放检查](https://github.com/engeeeee/ENGE-SPX/actions/runs/42657428237/artifacts/13693281655)。

## 已定位的断连原因

用户提供的 `guard.log` 显示：替换 `gateway/lease.json` 时发生
`WinError 5`。旧流程会将写入异常当作监测失败，停止状态或再次写入失败
均可能使后台续期中断，显示连接关闭或网关到期退出。没有 Shell 空闲计时。

新网关从 `lease.jsonl` 的有界尾部读取最后一条完整续期记录，宿主只追加
记录，不替换 Docker 正在读取的文件。半条记录不续期，明确的到期或撤销
记录覆盖旧记录；重新准备、旧网关停止后才重置日志。

其它 JSON 文件仍保持原子替换，对 Windows 短暂共享冲突最多重试三秒。
监测遇到 I/O 错误后三秒再试，不延长尚未成功写入的租约。持续故障依然
到期断网；撤销文件写入失败时，也继续调用 Docker 停止本环境。

此处的 Windows 共享语义参见 [Python 官方问题记录](https://bugs.python.org/issue46003)。
实际 Docker Desktop / WSL 挂载实现与第三方软件的长期占用仍需用户实机验收。

## 网络改动与范围

出口检测复用已有的只读隔离会话，减少临时容器创建；双出口来源及直接
出网阻断并行检查。仅连接检查和确认时查询地理信息，后台不反复请求。
仍核对出口与拓扑，发现变化或检测失败仍停止，不增加 DIRECT 或故障回退。

本机代理的多路传输使用每流八帧接收信用，单帧最多 64 KiB、最多 64 流，
为 EOF 保留独立位置。慢接收者不会堵住其它流的帧解析；保留精确 0.2
旧网关的原协议兼容。浏览器显示开启两秒重连，延长 Pong 等待，并在本机
VNC socket 开启 `TCP_NODELAY`。

这些检查证明调度、边界与协议行为，不构成用户线路的带宽或延迟测速。
双跳距离、加密、Docker 桥接和远程画面传输仍有成本，不能承诺固定提速。
[noVNC 重连参数](https://github.com/novnc/noVNC/blob/master/docs/EMBEDDING.md)
只重建显示连接，不会重新启动 Docker 或自动确认新出口。

## 字体与中文

新浏览器镜像移除预装的 `fonts-noto-cjk`，保留 Liberation、DejaVu 和 Emoji。
网页自己的 Web 字体仍可加载，部分中文网页可能缺字。此改动减少预装字体
信号，不代表网站无法识别环境或关联身份。

项目镜像配方保持 `6e3fcfa5633c`，不添加 CJK 字体包，UTF-8 locale 保留。
Windows 终端负责绘制中文，容器内的字符输入输出仍有效；工具仍能看到
发送给它的中文与环境语言，个别终端支持字体查询，所以不承诺字体不可见。
参见 [Windows 终端协议](https://learn.microsoft.com/en-gb/windows/console/classic-vs-vt)
及 [xterm 字体操作](https://invisible-island.net/xterm/manpage/xterm.html)。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| Windows Python 3.12 | 运行 143 项测试，2 项按平台跳过，其余通过 |
| Linux Python 3.12 | 运行 143 项测试，8 项按平台跳过，其余通过 |
| 真实 Windows 共享句柄 | 拒绝删除共享的句柄确实阻止 `os.replace`，追加续期仍成功；关闭句柄后普通 JSON 原子替换重试成功 |
| 续期与停止 | 不完整尾部、明确撤销、持续拒绝的重试上限、监测 I/O 失败后恢复、撤销写入失败仍停止 Docker 均通过 |
| 转发 | 多流大数据和半关闭通过；慢流占满接收窗口及 EOF 位置时，其它流仍可交付数据 |
| 无 Shell 输入 | 真实 Docker 环境持续 190 秒，无工具启动或前台续期；后台心跳持续推进，网关、会话、浏览器和显示页面均保持可用 |
| 字体与中文 | 实际浏览器 `fc-list :lang=zh family` 输出为空；项目容器的真实 PTY 完成中文 UTF-8 输入输出往返 |
| 浏览器显示 | 重复建立 VNC 显示连接成功；错误令牌与外部 Origin 仍被拒绝 |
| 隔离和资料 | 双出口、直连阻断、授权回调、网关租约到期、停止及数据迁移后项目、工具层和浏览器资料保留通过 |
| Windows 分发 | 原生 Qt、125% / 150% / 200% 缩放、打包程序默认不启动 Docker、安装卸载与私有数据保留通过 |
| 运行环境归档 | containerd 与 classic 两种镜像存储完成校验、导入和重复安装，保留已有标签与容器数据 |

没有固定挂机时长上限。180 秒是最后一次成功续期后的保护期限；只要后台
持续通过检查并写入续期记录，就不会因未操作 Shell 而到期。本次真实容器
测试覆盖 190 秒，尚不等于用户 Windows / WSL 环境下连续数天的实机测试。

## 公开下载核验

发布后使用程序相同的 HTTPS 客户端，从公开地址完整下载安装版、便携版、
运行环境清单与校验文件。长度和 SHA-256 均匹配 GitHub 资产摘要；便携
ZIP、两个 x64 入口的版本信息、Qt 许可证、新出口检查脚本、租约读取程序
及精简后的浏览器配方均已检查。

| 资产 | 字节数 | SHA-256 |
| --- | ---: | --- |
| ENGE-SPX-Windows-x64-0.8.2-Setup.exe | 32,201,148 | `acd80c6755e337a96b0b9c7c594ade9df1f8a5beddbbea0e6a9d4303c2219a7f` |
| ENGE-SPX-Windows-x64-0.8.2-Portable.zip | 50,466,941 | `6e550ce4bcf741803ee3b87982e534840d416e5dfd90559fbda5a676c7f03701` |
| ENGE-SPX-Runtime-linux-amd64-0.8.2.tar.gz | 875,930,746 | `400c5adb4e51a4ad76ceca3f4d66a4a882644ba8a9a86df621dd005d84d24fe9` |

完整运行环境已在 CI 校验并导入两种镜像存储，发布后未在本地重复完整
下载。公开清单的配方与源码一致，归档长度及摘要匹配 GitHub 元数据，
公开 Range 请求返回正确总长度与有效 gzip 头。

## 升级

先退出旧版，再更新程序并点击“一键准备环境”，获取新的网关和浏览器
镜像。仅更新 exe 而继续运行旧浏览器，不会移除旧镜像的字体。

已有匹配的项目镜像、项目容器、工具账号卷和浏览器 profile 保留，无需
删除 Docker 数据。原生 Linux 容器集成和临时假 Desktop 检查不替代用户的
Docker Desktop / WSL、Pebrel、v2ray 与显示器组合验收。

安全范围继续见 [安全模型](security-model.zh-CN.md)，常见问题见
[FAQ](faq.zh-CN.md)。
