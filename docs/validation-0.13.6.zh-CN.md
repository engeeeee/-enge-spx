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

最终 Windows、冻结包、真实 Docker 及公开附件结果在实际完成后记录；未运行不计通过。Windows WSL 命令输出为夹具，不代替报告设备的真实 Desktop / WSL2 验收。配置、管理接口或系统证据仍不可用时保留界面，并提供具体失败分类。

## 性能

没有常驻进程、监听或采样频率变化。退出期间读取有限配置文件，隐含后端增加两次小范围只读注册查询。固定配置拒绝取消无意义重复；临时读取错误仍在原预算内重试。没有用户设备的 CPU/内存/退出耗时对照，不声称提升百分比。
