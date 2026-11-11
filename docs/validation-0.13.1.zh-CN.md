# 0.13.1 正式版交付与验证

按维护者要求，将当前功能发布为正式版，随后根据实际使用反馈继续优化。2026-11-11 已发布 [ENGE SPX 0.13.1](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.1-windows)，GitHub `prerelease=false`、`draft=false`，并由 `/releases/latest` 确认其为 Latest。发布提交/标签为 `e27f6579d0033915e6bd98808cee10a77496e5d1`。基线为 0.13.0 及其发布后文档提交 `0e18a3d9cba9502bbcc7098d6edaddaa5e0b7d8a`。未运行、跳过和待实机验收不算通过。

## 1. 修改概述

版本升级为 0.13.1，统一桌面页脚、关于页面、Windows GUI/CLI 的产品版本与正式版标志，GitHub 发布为完整版本并设为 Latest。保留原有功能、配置、身份、账号、资源预算、退出偏好、镜像配方和许可证。

## 2. 涉及文件

`src/enge_spx/__init__.py`、`ui/window.py`，Windows 的 `version-info.txt`、`cli-version-info.txt`、`Installer.iss`，`.github/workflows/ci.yml` / `security-p0.yml`、`tools/publish_release.cjs`、`tests/test_release_publication.cjs`，README、SECURITY、CHANGELOG、贡献/开发/安全说明和正式版发布说明。没有改动容器配方、代理/凭据/数据迁移或运行时依赖。

## 3. 技术方案

现有完整 CI 仍先验证 Windows/Linux、冻结程序、安装卸载、实际容器和导出归档的双镜像存储导入，再调用发布助手。发布时保留 draft，全部七个经过校验的附件上传后才设置 `draft=false`、`prerelease=false`、`make_latest=true`。已有附件不替换；校验和或来源提交不一致时拒绝更新。

Windows 两个 EXE 清除 VS_FF_PRERELEASE，产品和文件版本都为 0.13.1，冻结打包检查核对二者及预发布标志。Node.js 测试只用于开发/CI，没有加入应用依赖。

Linux 单元测试与发布辅助机器固定为 `ubuntu-24.04`，真实容器集成固定为 0.13.0 已验证的 `ubuntu-26.04`。首次 `ubuntu-latest` 实际选择 Ubuntu 26.04，在应用测试前因 Ubuntu 软件源域名解析失败退出，单项重跑仍停在相同步骤；固定 24.04 后也记录到相同域名解析错误。因此仅将临时 CI 机器的 Ubuntu mirror list 改为 Kernel.org HTTPS 镜像，保留原 Ubuntu 源发行版、官方签名密钥及 APT 验证，保留 HTTPS 证书验证。单元测试通过后，24.04 容器集成的旧普通网络夹具在指定固定 IP 时被 daemon 拒绝，尚未进入升级/防泄漏断言；恢复容器集成的原已验证平台并完整重跑。没有改变应用、容器配方、代理下载设置或测试要求。

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

本地 Linux ARM64 的 Python 测试发现 365 项，353 通过、12 项 Windows 专用跳过；Qt smoke 和 200% DPI 全部既有控件检查通过。仓库版本、元数据、65 篇文档链接与 diff 检查通过。

[最终同次完整 CI](https://github.com/engeeeee/ENGE-SPX/actions/runs/43041332357)全部通过：Windows 365 项（361 通过、4 跳过），Linux 365 项（353 通过、12 跳过），两平台各 9 项发布助手测试，Windows Qt smoke、125%/150%/200% 布局、冻结 Python 3.12、GUI/CLI 的 0.13.1 FileVersion/ProductVersion 与非预发布标志、真实 DPAPI 迁移/删除、手动 Docker 启动、安装及卸载保留数据。冻结 GUI 首屏记录 799 ms，仅为该次 runner 的观察。

实际 Docker 门禁保留所有断言，通过资源预算/记录、只读项目/身份卷、网络迁移回滚、DNS/UDP/IPv6/宿主阻断、真实协议/TLS/Reality/QUIC 及断线、Chromium 内核沙箱、拒绝无沙箱回退、中文 PTY、190 秒浏览器独立续期、Cookie/Storage 与账号恢复、双跳出口异常停机、身份/诊断/按需测速，以及导出归档在 containerd 和经典 Docker 镜像存储中的再次导入。公网测速结果为 `checked`，前后核验均 `verified`；不冒充真实 AI 账号或用户设备验收。

发布在全部门禁完成后执行。七个公开附件齐全；安装版和便携版已实际下载，文件大小、公开 SHA-256/GitHub digest、ZIP CRC 与必需资源核验通过。便携包两个 EXE 的 PE 固定版本均为 `0.13.1.0`，flags 均为 0；测速脚本与已测试源码一致（规范化行尾）。原 0.13.0 的附件 ID、大小、digest 和来源提交保持原样。

| 公开附件 | bytes | SHA-256 |
| --- | ---: | --- |
| `ENGE-SPX-Windows-x64-0.13.1-Setup.exe` | 32,448,615 | `5f998a434970e3d7e1472c3c7b4628413c186f4cbefa75abf31b77a0dc2a1008` |
| `ENGE-SPX-Windows-x64-0.13.1-Portable.zip` | 50,969,405 | `e08e58a2f9c632d65c7bcd21c7b97749fe25a2c003a26a9d2f3355593eb06ef2` |
| `ENGE-SPX-Runtime-linux-amd64-0.13.1.tar.gz` | 875,936,804 | `b42d7762fe95cde8a8ac1c6d43fc35cb120ecc9afaf3d08716b591dd710add3d` |

公开 runtime manifest 的平台、镜像/config 标识和配方核验通过，大小与 digest 对照同次 CI 已导入验证的导出 SHA 一致，没有再次下载整份 runtime。配方仍为 gateway `9aa8a7818569`、work `6e3fcfa5633c`、browser `1bca0984bc51`。

## 6. 性能与磁盘

只有版本/展示/发布标识变化，不增加后台任务、生产依赖、端口或完整虚拟机。同次 Linux Docker runner 依次运行 0.13.0（`859e75b`）正常、0.13.1 正常和低资源独立 worker，共用已验证的镜像；各阶段两份样本均值如下。内存仅为运行中的本实例容器 Docker 统计之和，CPU 为单核百分比，不能与主机/WSL2 内存相加。

| 观察 | 0.13.0 正常 | 0.13.1 正常 | 0.13.1 低资源 |
| --- | ---: | ---: | ---: |
| 默认 CLI 启动后容器内存（MiB） | 249.924 | 249.505 | 17.923 |
| 该阶段容器 CPU 合计（%） | 0.375 | 0.315 | 0.030 |
| Chromium canvas 内存（MiB） | 282.156 | 280.578 | 282.867 |
| 默认 CLI 启动（ms） | 3,717.222 | 3,526.707 | 1,243.825 |
| 工作区完全停止（ms） | 1,132.590 | 676.265 | 1,207.017 |
| 完全停止后运行容器 / 内存 | 0 / 0 | 0 / 0 | 0 / 0 |

低资源已有浏览器延迟启动，因此 CLI 阶段少一个浏览器，canvas 阶段已显式启动；不是本批新增节省。三组项目层均为 8,413,184 B（含合成 8 MiB 写入），browser/session/gateway 层分别为 4,096/4,096/8,192 B。资源 artifact ZIP SHA 已核验为 `923debc90940a4d14e3d02f79be6e8ddd40ccf8b02f76c4d2fe28975532cf661`，其中保存完整 JSON。

短样本、启动残留活动和缓存会影响数字，不以版本标识变化声称收益。不包含真实模型请求、已连接 noVNC 客户端、物理 Windows/WSL2 性能或所有卷/虚拟磁盘；长期数据增长和体验按用户后续实际使用反馈验证。

## 7. 遗留边界

Windows 包仍未签名，未经过独立安全审计。用户 Docker Desktop/WSL2/v2ray/终端/显示器组合和真实 AI/noVNC 长期体验继续通过实际使用反馈验证。项目许可、容器/宿主信任边界及已有协议范围保持不变。

## 8. 后续工作

先使用正式版，按 [实机验收步骤](windows-acceptance.zh-CN.md)保存需要的脱敏记录；后续围绕可复现问题做小范围修复和优化。本次不加入新的协议、指纹调整或系统设置变更。
