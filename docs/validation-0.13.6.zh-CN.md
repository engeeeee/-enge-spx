# 0.13.6 默认 WSL2 退出核验

## 反馈与根因范围

0.13.5 的实机诊断确认离线预算已可用，但连续在 `wsl2_configuration/not_confirmed` 被拒绝，没有执行进程、管道与 WSL 检查。源码要求用户设置文件显式含有 true，遗漏 Docker 允许的默认配置。报告没有提供原文件，不能断言用户一定省略了字段；本版同时覆盖已知格式、层次和查找失败分类。

[Docker 设置参考](https://docs.docker.com/desktop/enterprise/hardened-desktop/settings-management/settings-reference/#enable-wsl-engine)列明 WSL2 默认开启；[安装参数](https://docs.docker.com/desktop/setup/install/windows-install/#installer-flags)允许选择不同后端；[管理设置](https://docs.docker.com/desktop/enterprise/hardened-desktop/settings-management/configure-json-file/)有锁定/默认与用户覆盖区别。因此不能仅把缺失键改成无条件 true，也不能离线假定矛盾的策略已生效。

## 文件与技术方案

- `desktop_settings.py`：只读、限量、拒绝重复键/非法常量的 JSON 解析；当前与旧用户文件择一、安装与管理层、大小写和包装/分组值；支持系统目录查询回退。拒绝缺失文件、损坏、不可读及明确其它后端，输出固定原因，不采集其它设置用于诊断。
- `desktop_offline.py`：默认/安装等隐含选择增加当前用户 Docker 发行版 Version=2 的只读注册证据，只读取发行版 GUID 子项，跳过 DiskMounts 等元数据，结合原完整停止条件；收尾前重读配置/注册，再完成最终进程/管道检查。20 秒/8 秒和可选 60 秒预算不变，读取竞争有界重试，显式拒绝不空等。
- Desktop 设置及离线测试：真实格式缺省 JSON、大小写/分组、策略/安装覆盖与矛盾、缺失/权限/损坏/过大/重复键、WSL1/WSL2 注册、最终状态变化与报告脱敏。
- Windows 完整 Engine.shutdown 回归：使用真实临时设置文件、测试自有 HKCU 子树、原生进程快照和私有命名管道；只注入管理接口不可用与 WSL 输出，不把配置读取替换为 True；核验授权撤销、敏感引用清理、账号保留和最终停止。
- 既有冻结 CLI `--self-test` 同时加载新设置模块并执行纯默认/禁用解析，避免仅在源码测试成功却遗漏打包依赖；不读取或修改真实 Docker 设置。

没有更改镜像、运行依赖、权限、网络策略、工具启动/更新、配置格式或许可证。注册表只读；测试只创建/删除自己的独立测试子树。不会为退出启动 Docker 或修改其开关。回滚不需要逆迁移，但旧版仍缺少本次默认配置识别。

## 验证命令

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_desktop*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/check_repository.py
node --test tests/test_release_publication.cjs
PYTHONPATH=src python tools/smoke_gui.py
```

本地 Linux ARM64 完整回归 436 项：417 通过、19 项 Windows 专用跳过，约 16.0 秒。9 项发布助手检查、Qt GUI smoke、77 篇文档/版本及 diff 检查通过。三个镜像配方及 0.13.5 的工具更新/终端/Engine 代码保持不变；唯一 CLI 增量是上述打包自检。

[最终 CI #43368293593](https://github.com/engeeeee/ENGE-SPX/actions/runs/43368293593) 的 Windows、Linux、冻结包、容器和发布任务全部成功，源码为 `cb43e21bae4e9def4dedd2e316626bea0761ef46`。Windows 436 项：429 通过、7 项跳过，约 99.7 秒；Linux 436 项：417 通过、19 项跳过，约 19.4 秒。两个平台各 9 项发布助手检查通过，Qt smoke 和 125% / 150% / 200% DPI 通过。

Windows 原生临时设置文件、GUID 发行版与 DiskMounts 元数据的测试自有注册表、完整 Engine.shutdown、当前用户目录回退均实际运行通过，未以跳过计通过。冻结 CLI 自检加载新解析模块，GUI 手动启动、托盘/联合退出、Docker 先关闭、DPAPI、安装卸载数据保留及正式版本检查通过。

Docker 的预算/记录/身份/只读挂载、DNS/UDP/IPv6 阻断、TLS/Reality/gRPC/QUIC 和固定链路故障、原生 Chromium 沙箱、中文 PTY、190 秒无 Shell 输入续期、两个官方 CLI 的用户目录安装与迁移持久化均通过。归档在 containerd/classic 两种镜像存储下导入并实际启动通过。同次性能记录保留历史基线与候选 normal/low 七阶段，不是客户 Windows 0.13.5→0.13.6 的性能对照。

注册格式已核对 Microsoft 的 [DistributionRegistration.h](https://github.com/microsoft/WSL/blob/b60fc4ee367e0b37ab8426ecfc93cdd258552f20/src/windows/service/exe/DistributionRegistration.h) 和 [wslservice.idl](https://github.com/microsoft/WSL/blob/b60fc4ee367e0b37ab8426ecfc93cdd258552f20/src/windows/service/inc/wslservice.idl)。Windows WSL 命令输出仍为夹具，不代替报告设备真实 Desktop / WSL2 验收；用户原配置未采集，不能宣称所有匹配错误均已覆盖。未知或失败证据仍保留界面并给出具体分类。

## 性能

没有常驻进程、监听或采样频率变化。退出期间读取有限配置文件，隐含后端增加两次小范围只读注册查询。固定配置拒绝取消无意义重复；临时读取错误仍在原预算内重试。没有用户设备的 CPU/内存/退出耗时对照，不声称提升百分比。

## 发布包复核

[0.13.6 正式版](https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.6-windows) 已公开，非草稿、非预发布，且为 GitHub 最新正式版；标签指向上述最终源码。

| 附件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| Setup | 34,396,895 | `4a60f21b1ebb78eb9e1646005aff13e792b4e6f94700221331600f9f92a2b862` |
| Portable | 52,978,511 | `e86a558dabd838ee17c0b5b032f9483f5742539e26c0b45331770f72e13edfa7` |
| Runtime linux-amd64 | 875,929,531 | `f1f790d092c08d96c88df84dcb45a36587d0cf827462e2f90f18b12d94359511` |

实际下载 Setup 和 Portable，字节数、公开 SHA 文件、GitHub digest 与本地哈希一致，ZIP CRC 正确。两个 EXE 的 File/ProductVersion 均为 `0.13.6.0`，正式版本标记正确；冻结归档确认包含 `desktop_settings` 默认值解析、`desktop_offline` 注册核验及原有用户工具更新和退出诊断模块。运行环境不重复下载：公开清单、大小/digest 与同次 CI 导出及两种镜像存储导入证据一致。三个镜像配方不变，0.13.5 已发布安装包/便携包校验值保持不变。
