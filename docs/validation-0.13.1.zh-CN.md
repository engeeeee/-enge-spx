# 0.13.1 正式版交付与验证

按维护者要求，将当前功能发布为正式版，随后根据实际使用反馈继续优化。基线为 0.13.0 及其发布后文档提交 `0e18a3d9cba9502bbcc7098d6edaddaa5e0b7d8a`。本页按实际进展补充 CI 与公开下载证据；未运行、跳过和待实机验收不算通过。

## 1. 修改概述

版本升级为 0.13.1，统一桌面页脚、关于页面、Windows GUI/CLI 的产品版本与正式版标志，GitHub 发布为完整版本并设为 Latest。保留原有功能、配置、身份、账号、资源预算、退出偏好、镜像配方和许可证。

## 2. 涉及文件

`src/enge_spx/__init__.py`、`ui/window.py`，Windows 的 `version-info.txt`、`cli-version-info.txt`、`Installer.iss`，`.github/workflows/ci.yml` / `security-p0.yml`、`tools/publish_release.cjs`、`tests/test_release_publication.cjs`，README、SECURITY、CHANGELOG、贡献/开发/安全说明和正式版发布说明。没有改动容器配方、代理/凭据/数据迁移或运行时依赖。

## 3. 技术方案

现有完整 CI 仍先验证 Windows/Linux、冻结程序、安装卸载、实际容器和导出归档的双镜像存储导入，再调用发布助手。发布时保留 draft，全部七个经过校验的附件上传后才设置 `draft=false`、`prerelease=false`、`make_latest=true`。已有附件不替换；校验和或来源提交不一致时拒绝更新。

Windows 两个 EXE 清除 VS_FF_PRERELEASE，产品和文件版本都为 0.13.1，冻结打包检查核对二者及预发布标志。Node.js 测试只用于开发/CI，没有加入应用依赖。

发布工作流的 Linux 机器固定为 `ubuntu-24.04`。首次 `ubuntu-latest` 实际选择 Ubuntu 26.04，在应用测试前因 Ubuntu 软件源域名解析失败退出，单项重跑仍停在相同步骤；固定 24.04 后也记录到相同域名解析错误。因此仅将临时 CI 机器的 Ubuntu mirror list 改为 Kernel.org HTTPS 镜像，保留原 Ubuntu 源发行版、官方签名密钥及 APT 验证，保留 HTTPS 证书验证，再重新执行完整门禁。这不改变应用、容器配方、代理下载设置或测试要求。

## 4. 已实现功能与兼容

正式版保留 Chromium 沙箱、DPAPI、固定代理链路和双出口核验、异常停机、身份隔离、只读/读写项目授权、资源预算/记录、网络诊断及按需测速。打开软件不自动启动 Docker，X 隐藏到托盘，真正退出默认停止工作区，可显式选择正常关闭 Docker Desktop。没有持久配置迁移，旧镜像和账号可继续使用。

## 5. 测试命令及实际结果

```bash
node --test tests/test_release_publication.cjs
python tools/check_repository.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/smoke_gui.py
QT_SCALE_FACTOR=2 PYTHONPATH=src python tools/check_ui_dpi.py
```

新增发布助手的 9 项测试已在本地 Node.js 22 通过：全部附件上传后正式发布、已验证预览版提升、正式版重复执行不重传或回退 Latest、附件不符/缺失拒绝、错误来源提交拒绝、本地 Windows 校验和/运行归档异常在 API 请求前失败、其它仓库/分支拒绝。

本地 Linux ARM64 的 Python 测试发现 365 项，353 通过、12 项 Windows 专用跳过；Qt smoke 和 200% DPI 全部既有控件检查通过。仓库版本、元数据、65 篇文档链接与 diff 检查通过。Windows 打包、完整 Docker 和公开下载结果待本次 CI 执行后补记。发布继续经过原有门禁，不以正式版标识替代这些检查。

## 6. 性能与磁盘

只有版本/展示/发布标识变化，不增加后台任务、生产依赖、端口或完整虚拟机。本次不以标识变化声称速度、CPU、内存或磁盘收益。同次 CI 继续保留 0.13.0 基线、候选正常与低资源容器阶段原始对照；不等同于真实 Windows/WSL2 或 AI/noVNC 性能。

## 7. 遗留边界

Windows 包仍未签名，未经过独立安全审计。用户 Docker Desktop/WSL2/v2ray/终端/显示器组合和真实 AI/noVNC 长期体验继续通过实际使用反馈验证。项目许可、容器/宿主信任边界及已有协议范围保持不变。

## 8. 后续工作

先使用正式版，按 [实机验收步骤](windows-acceptance.zh-CN.md)保存需要的脱敏记录；后续围绕可复现问题做小范围修复和优化。本次不加入新的协议、指纹调整或系统设置变更。
