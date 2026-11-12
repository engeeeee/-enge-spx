# Windows 界面截图与复现

README 中的四张图片来自 **ENGE SPX 0.13.2 在原生 Windows 环境运行的真实 Qt 界面**。截取工作台、项目工作区、连接与代理、资源预算页面，PNG 原图保留，不经过图像生成、拼接或添加虚构状态。

| 项目 | 记录 |
| --- | --- |
| 截图时间 | 2026-11-11 16:27 UTC |
| 平台与工具 | Windows、Python 3.12.10、PySide6 6.12.0、100% Qt 缩放 |
| 运行源码 | `990d97eae580e99e3c22db454adb878dec76b90c`；应用源码与 0.13.2 正式版一致 |
| 窗口大小 | 1280 × 1000 |
| Windows 任务 | [README Windows screenshots / 43058430309](https://github.com/engeeeee/ENGE-SPX/actions/runs/43058430309) |
| 文件清单与 SHA-256 | [capture.json](../images/0.13.2/capture.json) |
| 原始 artifact SHA-256 | `cda8e2caeef5801e24155617e8731e9a3eace7a3030656f1147a33ccb7429a46` |

截图使用临时、未配置的数据目录，没有填写真实账号、节点凭据、出口或个人项目，也没有启动 Docker 工作区。尚未确认连接时，工具按钮显示为禁用，这是正常状态。它们展示界面和功能入口，不作为真实账号登录、代理连通性或用户设备长时体验的证明；功能验证另见 [0.13.2 交付报告](../validation-0.13.2.zh-CN.md)。

## 原图

- [工作台](../images/0.13.2/overview.png)：环境准备、出口信息与工作区路径。
- [项目工作区](../images/0.13.2/workspace.png)：项目目录、身份、访问权限及工具入口。
- [连接与代理](../images/0.13.2/connection.png)：落地、前置线路与本机代理配置。
- [资源预算](../images/0.13.2/resources.png)：各环境 CPU、内存上限和浏览器启动选项。

## 重新截取

在已安装项目依赖的 Windows 源码目录执行：

```powershell
$env:PYTHONPATH = 'src'
$env:QT_SCALE_FACTOR = '1'
python docs/screenshots/capture.py --output .\build\readme-screenshots
```

脚本打开真实窗口，在临时应用数据目录中切换页面、检查品牌及工具按钮未被裁切，保存 PNG 和 `capture.json`，最后关闭窗口。它不会点击启动、连接检查、登录或工具按钮，不会使用现有用户数据。

[专用 workflow](../../.github/workflows/readme-screenshots.yml)可手动运行；修改截图脚本时也会自动运行。它只生成文档截图，不构建或发布软件版本。其它平台可运行脚本预览排版，`capture.json` 会如实记录平台；更新 README 的 Windows 图时应使用 Windows 产物。

历史图片仍保留在 `docs/images/spx-*.png`，供旧版本文档引用。

## 官网高清版本（2×）

官网使用原生 Windows 2× DPI 重新截取的 2560×2000 PNG，逻辑窗口仍为 1280×1000，软件内部布局不改动。它们是软件重新渲染的截图，不是对 1× 图片进行插值或 AI 放大。

- [原生 Windows 任务 43168136679](https://github.com/engeeeee/ENGE-SPX/actions/runs/43168136679)
- [高清文件清单、逻辑尺寸、DPR 与 SHA-256](../images/0.13.2/2x/capture.json)
- [工作台](../images/0.13.2/2x/overview.png) · [项目工作区](../images/0.13.2/2x/workspace.png) · [连接与代理](../images/0.13.2/2x/connection.png) · [资源预算](../images/0.13.2/2x/resources.png)

捕获时间 2026-11-12 06:27 UTC，源码 `f607efda4fbbd839a2ed710fce48e7637d73fe20`，应用版本 0.13.2。复现时设置 `QT_SCALE_FACTOR=2`；这是当时的 2× 捕获配置；当前专用 workflow 使用下面的官网适配配置。原始 1× 文件保留供历史记录使用。

## 官网尺寸适配版本（3×）

为避免在普通 1080p 显示器上将完整宽窗口过度缩小，官网使用真实软件的响应式窗口重新截取各页面。工作台、连接和资源页面显示软件本身已有的紧凑导航；项目页保留完整导航。仅改变真实窗口尺寸和 Windows Qt DPI，没有改变字体、控件、状态或应用源码。

| 页面 | 逻辑窗口 | PNG 原始像素 |
| --- | --- | --- |
| 工作台 | 960×840 | 2880×2520 |
| 项目工作区 | 1120×1050 | 3360×3150 |
| 连接与代理 | 840×1050 | 2520×3150 |
| 资源预算 | 840×1000 | 2520×3000 |

- Windows 捕获时间：2026-11-12 07:12 UTC。
- [原生 Windows 任务 43173501032](https://github.com/engeeeee/ENGE-SPX/actions/runs/43173501032)，源码 `90a7fec5be471c24b0ff2edffb69d9972232c790`，应用仍为 0.13.2。
- [原图清单与 SHA-256](../images/0.13.2/web-3x/capture.json)。
- 原始 artifact SHA-256：`f9837bbb0b5de333971ec03f6bbf317a850baa76af68c8eec508f2edb7d23eeb`。
- [工作台](../images/0.13.2/web-3x/overview.png) · [项目工作区](../images/0.13.2/web-3x/workspace.png) · [连接与代理](../images/0.13.2/web-3x/connection.png) · [资源预算](../images/0.13.2/web-3x/resources.png)。

复现：

```powershell
$env:PYTHONPATH = 'src'
$env:QT_SCALE_FACTOR = '3'
python docs/screenshots/capture.py --profile website --output .\build\website-screenshots
```

官网首页展示区允许裁切窗口底部，点击可查看完整 PNG。普通 DPI 屏幕不对软件图片做透视变换，立体效果由独立背板和阴影承担；高 DPI 屏幕保留轻微透视。1×、2× 和本批原图分别保留，README 仍引用完整导航的 2× 图。
