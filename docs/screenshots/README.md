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
