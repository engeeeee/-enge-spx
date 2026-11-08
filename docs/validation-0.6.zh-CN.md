# 0.6.0 一键准备与发布验证

验证日期：2026-11-08。当前版本为 **0.6.0 Preview**。

- [发布与下载](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.6.0-windows)
- [完整成功构建](https://github.com/engeeeee/ENGE-SPX/actions/runs/42516934275)
- 受测代码与发布标签均指向 `f08eb1dd502b5d3f0f5b7650b952f3c5c4a0f5e3`。

## 检查结果

| 检查 | 结果 |
| --- | --- |
| Windows Python 3.12 | 115 项测试通过，2 项按平台跳过 |
| Linux Python 3.12 | 115 项测试通过，4 项按平台跳过 |
| 启动控制 | 已运行引擎复用、Desktop 启动一次并等待、首次上下文建立、错误配置拒绝、超时、取消和已有数据保留通过 |
| Windows 原生进程 | 编译独立假 CLI / Desktop，在含空格的自定义目录验证旧 CLI 回退和延迟就绪；不启动 CI 主机真实 Desktop |
| 源码 GUI | 页面渲染、异步准备时响应、取消、节点配置引导、数据迁移和安装标识保留通过 |
| Windows 打包 | CLI 资源自检、代理依赖、图标与产品名、GUI 首次显示、用户级安装、快捷方式、卸载保留私有数据通过 |
| 真实 Linux Docker | 两个出口来源核对、阻断工作容器直接 TCP 出网、网关故障阻断通过 |
| 代理链路 | HTTP 本机前置＋认证落地、软件内加密前置、线路失效不回退、NO_PROXY 污染防绕过通过 |
| 预构建环境 | containerd 和 classic 存储均完成完整归档导入、重复安装、已有标签与数据保留检查 |
| 仓库文件 | 版本、仓库地址、About 期望配置和 24 份文档的本地链接通过；About 脚本 `-WhatIf` 通过 |

Windows 打包 GUI 在本次 CI 中首次显示为 **2471 ms**。这只是该 runner 的窗口绘制耗时，不包含 Docker 首次初始化、下载或连接检查，不代表所有电脑的启动速度。

第一轮 Windows 检查因新增测试对路径分隔符的断言失败而阻止发布；修正并补齐启动进程回收后，以上最终构建完整重跑通过。没有发布未经该流程验证的 0.6.0 资产。

## 公开下载核验

发布后通过程序使用的 HTTPS 客户端，从新仓库公开地址完整下载安装版、便携版、清单与校验文件；大小、SHA-256 和发布元数据一致。便携版解压完整性、GUI / CLI 的 x64 PE 架构与 `0.6.0 Preview` 版本信息，以及包内中文主页、快速入门、安全说明、截图和许可证均已检查。

| 资产 | 字节数 | SHA-256 |
| --- | ---: | --- |
| ENGE-SPX-Windows-x64-0.6.0-Setup.exe | 15,735,376 | `7783b6a01132bee22dbdcb2a83cf49465bcc0b965d6f3c7346e7f71b0d4897b8` |
| ENGE-SPX-Windows-x64-0.6.0-Portable.zip | 21,856,396 | `8b6a1bf47a90b8c455c7f450dfe6727b2125c338ff33a8a6f80ec55f7c30dabd` |
| ENGE-SPX-Runtime-linux-amd64-0.6.0.tar.gz | 949,402,094 | `39efd6774604623142cb96086addfe56c4c8ecd1e25b81efd4d05341f6e2bb89` |

约 949 MB 的完整 runtime 已在 CI 校验、导入并在两种存储中检查。本地没有在发布后再次完整下载该大归档；公开清单与源码配方、GitHub 资产摘要和 CI 摘要一致，公开 Range 请求返回正确总长度并能读取 gzip 内容。

## 验证边界

原生 Windows 假进程检查不等于真实 Docker Desktop / WSL 首次安装交互，也没有在用户的 v2ray、Pebrel、线路服务商和账号组合上验收。项目读写共享、共享账号、Chromium `--no-sandbox`、凭据存储和监测周期等限制继续存在，详见 [安全模型](security-model.zh-CN.md)。

GitHub 右侧 About 是单独的仓库设置；当前连接不提供其写操作。版本化中文配置和维护者同步脚本已经提交，不能据此声称线上 About 已更新，见 [仓库简介设置](repository-settings.zh-CN.md)。
