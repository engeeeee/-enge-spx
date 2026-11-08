# ENGE SPX 0.3.0 验证记录

日期：2026-11-08。被构建和测试的应用代码提交：
`96bc5f19b5f0baeffd73003189e4c82967254cd9`。

- [发布与下载](https://github.com/engeeeee/-enge-spx/releases/tag/v0.3.0-windows)
- [成功的完整构建](https://github.com/engeeeee/-enge-spx/actions/runs/42452653604)
- [品牌与界面](branding.zh-CN.md)

## 独立项目与标识

GitHub 仓库元数据已核对，`fork` 为 `false`。提交从独立的许可证初始化提交
`c54b72d48857b5af94b97fda66f4216e9d06c74e` 开始，该提交没有父提交，没有继承原
fork 网络的提交历史。项目的设计参考与第三方来源仍在 NOTICE.md 中保留。

GUI、开始菜单、快捷方式、Windows 产品信息、安装目录、CLI、Python 包、
下载文件、Docker 新资源命名和项目首页均使用 ENGE SPX 标识。已生成新 SVG、
PNG 与多尺寸 ICO。旧名称仅保留在归属记录与数据升级兼容处理中。

## 已通过的检查

| 范围 | 结果 |
| --- | --- |
| Windows / Linux 单元检查 | 各 46 项通过 |
| Python 包 | wheel 构建成功，包含图标、容器配方、隐藏的 Docker ignore 文件和许可记录 |
| Windows 打包 | 原生 x64 GUI / CLI 构建、资源与代理依赖自检、窗口标题和 Windows 产品信息核对 |
| 安装卸载 | 当前用户安装、开始菜单快捷方式、已安装 CLI、卸载保留私有数据 |
| 原生 Linux x64 容器 | 实际构建并运行网关、工具和 Chromium，出口核对、直连阻断、远程显示鉴权、localhost 授权回调 |
| 代理链 | 带认证 HTTP 前置线路 → 带认证 SOCKS5 / HTTP 落地；线路关闭后阻断，无直连兜底 |
| 预构建包 | 下载完整归档、校验、导入和重复安装，在 containerd 与独立 classic 存储中均通过，已有标签与容器数据保留 |

升级兼容检查覆盖默认旧目录复用、归属标签限制、保留旧镜像及容器层、新旧
运行协议路径选择、浏览器 profile 内容保留，以及旧后台监测退出后的接管。
这些是自动化兼容检查，不能替代真实 Windows 电脑上对已有账号的升级验收。

本次 Windows CI 的 GUI 初始化到首帧记录为 2,343 ms。计时不包含进程加载、
Docker Desktop 启动或首次下载，不代表其他机器的性能。

## 交付文件

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| ENGE-SPX-Windows-x64-0.3.0-Setup.exe | 15,354,009 | `c2dbe05c94eb23b69ade4a7bfa34ab0c84e2af581a1a2d868b5797632c284de2` |
| ENGE-SPX-Windows-x64-0.3.0-Portable.zip | 21,392,784 | `4d7749b09c64fd4aa670e83ade3dd76beb05b351da7c199b063b0654174ef74f` |
| ENGE-SPX-Runtime-linux-amd64-0.3.0.tar.gz | 949,372,622 | `d18e25f1605ea16355f2bb60ee217ab00406d0aece6bd4881cb482351a401d25` |

发布后使用应用自己的 HTTPS 下载客户端读取了公开运行环境清单，核对版本、
镜像配方及标识；同时从公开 Release 地址下载 Windows 安装版与免安装包，
校验实际内容及对应 SHA-256 文件。临时运行环境传输 Artifact 在正式发布后
清理，正式 Release 文件继续保留。

## 边界

此版本尚未代码签名，没有进行独立渗透测试，也没有在真实 Windows 11 +
Docker Desktop 桌面完成全流程交互验收。实际代理链测试覆盖 HTTP 前置与
SOCKS5 / HTTP 落地，HTTPS 落地的验证范围为配置和 TLS 参数。没有使用真实
Anthropic / OpenAI 账号登录或请求模型。

Chromium 使用 `--no-sandbox`，选中的项目可读写共享，工具账号在项目间共享。
改名与独立托管不改变这些隔离边界；详见项目使用说明。
