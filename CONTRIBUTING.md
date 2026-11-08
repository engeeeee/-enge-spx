# 参与 ENGE SPX

欢迎中文或英文的问题报告、文档改进和代码贡献。项目目前处于 Preview 阶段，贡献内容遵循现有 [PolyForm Noncommercial 1.0.0](LICENSE)，提交前请确认有权贡献所用代码和素材。

## 开始之前

先查看 [README](README.md)、[支持指南](SUPPORT.md)和已有 Issues。漏洞请使用 [安全报告流程](SECURITY.md)。较大的协议、存储或安全边界调整，建议先在 Issue 解释使用场景、预期行为和兼容性，减少重复实现。

## 本地开发

需要 Python 3.12+ 和 Tcl/Tk。在 Windows PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/smoke_gui.py
```

Linux 使用 `PYTHONPATH=src`；GUI 检查需要桌面显示或 `xvfb-run`。完整构建和显式 Docker 集成命令见 [开发说明](docs/development.md)。集成检查会创建临时 Docker 资源并访问公开 IP 检测服务，不应使用真实账号或节点凭据。

## 提交更改

- 让改动围绕一个清晰问题，说明触发条件、改后行为、验证结果和兼容性影响。
- 修改网络、凭据、数据迁移或启动控制时，验证失败、取消及已有数据的处理；不要只覆盖成功路径。
- 运行与改动相关的检查。版本变更需要同步 Python 版本、Windows 元数据、安装脚本与 CI 资产名称。
- 文档和截图应反映实际可用功能；安全描述要说明适用模式、检测周期和边界。
- 不要提交订阅链接、代理密码、令牌、个人数据目录或真实账号资料；截图和日志提交前先脱敏。

PR 描述请说明“解决什么问题、如何验证、是否改变持久数据或网络行为”。CI 包含 Windows / Linux 检查、Windows 打包，以及真实 Docker 集成；没有执行过的检查应明确写出。

交流时尊重使用者和贡献者，讨论具体行为和证据，避免人身攻击。维护者会依据可复现情况和项目范围处理贡献，不承诺响应时限。
