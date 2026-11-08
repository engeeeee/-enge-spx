# 0.4.0 存储与终端验证

日期：2026-11-08。发布代码提交：`ced0258b753b842b6a1c4c363e78be02d072f174`。

- [下载 0.4.0 Preview](https://github.com/engeeeee/-enge-spx/releases/tag/v0.4.0-windows)
- [完整成功构建](https://github.com/engeeeee/-enge-spx/actions/runs/42463588476)
- [设置与恢复说明](storage-terminal.zh-CN.md)

Windows 和 Linux 各执行 82 项检查，Windows 跳过 2 项、Linux 跳过 3 项平台专用检查，其余通过。Windows 实际执行了不同盘符之间的迁移测试：保留安装标识和断点文件，切换默认位置，清理原文件，并通过原路径重定向重新打开数据。目标目录的 Windows 访问权限设置也在这些实际迁移中执行。

其他迁移检查覆盖占用目录、路径重叠、空间不足、缺失磁盘、文件变化、复制校验失败、后台锁等待与超时、清理失败、默认位置记录写入失败和多次迁移。源 GUI 在 Windows CI 和本地 Linux 图形环境中完成了实际的检查、确认、迁移及界面路径更新流程。

终端检查覆盖 Pebrel 参数、优先发现顺序、手动终端缺失时拒绝静默回退、自定义参数、Unicode、空格、引号、反斜杠和 Windows Terminal 的分号。Windows 原生子进程测试实际核对了收到的参数、工作目录与环境变量。该测试使用捕获参数的进程，没有在 CI 中打开真实 Pebrel 窗口。

原生 Linux x64 Docker 集成先建立并确认代理出口，启动工作区和共享浏览器，在项目文件、工具数据卷、项目容器可写层和浏览器数据卷中写入测试标记。随后调用应用数据迁移，再次检查并启用连接，确认项目容器 ID、会话容器 ID 和镜像 ID 保持一致，原标记仍可读取；网关被重新创建，其 `/config` 实际挂载源变为新目录。

既有出口核对、VNC 认证、OAuth 回环连通、网关租约失效阻断和前置线路到落地代理测试也通过。约 949 MB 的环境归档在 containerd 与独立 classic Docker 存储中均完成实际下载、校验、导入、重复安装和已有数据保留检查。

Windows x64 的 GUI / CLI 打包自检、资源加载、产品版本、快捷方式、安装和卸载检查通过。已下载最终 Windows Artifact，确认 SHA-256、GUI / CLI 的 PE x64 架构及 0.4.0 产品信息。发布后用应用自己的 HTTPS 客户端重新完整下载两份公开 Windows 包并核对摘要；公开运行环境清单与源配方匹配，归档地址响应 Range 请求并报告预期总长度。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| ENGE-SPX-Windows-x64-0.4.0-Setup.exe | 15,392,763 | `b336a239e50e35019c8bc84e8295f6746a07b32cabda84c487aabb35f0a0646a` |
| ENGE-SPX-Windows-x64-0.4.0-Portable.zip | 21,471,321 | `3a1cd6261de9d3aab75ae7da821be28e8792358319bdaeace86e9a1254c90e4b` |
| ENGE-SPX-Runtime-linux-amd64-0.4.0.tar.gz | 949,390,465 | `f095bfd31f37ba0b14bf13c1e70382f606d0a22e23c70b63814bbf8098d286d0` |

Docker Desktop 的 VHDX 搬迁需要用户在其设置中确认；项目只提供迁移准备、位置检测与原资源存在性核验。Docker 设置文件在测试中没有被项目代码修改。CI 未执行真实用户桌面的 Docker Desktop 数据盘搬迁，也未验证用户的 Pebrel 版本、真实账号授权或登录会话。

容器配方与 0.3.1 保持一致，已安装且匹配的镜像会复用。无代码签名、Chromium 关闭自身沙箱、项目读写共享和工具账号共享等预览限制继续适用。
