# 0.13.4 关闭竞态与退出诊断

## 问题与实施范围

反馈只提供了缺失 `dockerDesktopLinuxEngine` 管道的 Docker 错误，未取得客户端版本与核验日志，不能确定反馈设备的实际失败条件。源码另有可复现的关闭竞态：管道消失后，管理接口仍为 stopping 或已不可用，而进程/WSL 稍后才结束；0.13.3 对第一份未完成快照立即返回 False。

本批修复这条可复现路径，并将诊断入口放到失败弹窗中，避免重复要求用户找文件。未知状态仍保留界面，未实施跳过停止验证的退出方案。

## 文件与架构

- `desktop_shutdown.py`：在 12 秒上下文/管理观察预算内等待 stopping→stopped；其它明确活动状态不被离线证据覆盖。
- `desktop_offline.py`：在剩余时限内最多等待 8 秒，重复完整配置、进程、管道与 WSL 证据；接受规则与 0.13.3 一致，失败只增加固定阶段日志。
- `exit_diagnostics.py`：使用 ContextVar 隔离退出工作线程，最多 64 条只含固定代码与系统错误码的观察，不采集原始命令/错误输出或私人名称。
- `ui/controller.py`：只在失败时原子保存 schema-1 本地报告；保存失败不掩盖原错误。复制摘要不访问 Docker，配置不可读时提供最小版本与本次检查。
- `ui/window.py`：工作区停止未核实的弹窗直接显示运行版本并提供重试、复制、返回；默认返回，无隐式仅退出操作。Desktop 确认恢复窗口也增加复制。
- 复用 Desktop、退出生命周期、GUI、资源和打包测试，并补充报告隔离/脱敏、真实自建 Windows 进程退场及两类恢复弹窗的 DPI 检查。

没有配置逆迁移或既有数据变更。账号、代理、身份、预算、退出偏好和镜像继续兼容。`logs/exit-diagnostics.json` 只是诊断记录，不参与授权；旧版忽略此文件。

## 测试

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_desktop*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_exit*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src QT_SCALE_FACTOR=2 python tools/check_ui_dpi.py
python tools/check_repository.py
node --test tests/test_release_publication.cjs
```

相同的模拟退场序列下，0.13.3 返回 False，候选的有界等待返回 True，且只在后续完整证据通过后成功。持续活动、重启、超时、权限不足、未知配置和不匹配上下文仍不能声称已停。本地 Linux ARM64 完整回归 415 项：399 通过、16 项 Windows 专用跳过，约 12.8 秒；9 项发布助手测试、Qt 200% 两种恢复弹窗/诊断按钮及 72 篇文档/版本检查通过。Windows、冻结包及正式发布结果在实际完成后补充，跳过/未执行不计通过。

Windows 延迟进程测试只创建并等待测试自有 Docker Desktop.exe 夹具，使用真实 Win32 快照和独立管道；WSL 数据注入，不操作用户 Docker。此测试不能冒充反馈设备真实 Docker Desktop / WSL2 验收。

## 性能与限制

无常驻采集、额外监听、生产依赖或镜像配方变化。重试只在退出时发生，工作线程等待、不占用 GUI 线程；离线观察间隔 250 ms，具有原有证据预算，联合关闭保留原总时限。不降低安全监测频率。不声称 CPU、内存或退出速度的提升百分比，真实设备仍可能在未知后端、权限或配置状态上拒绝退出，此时直接复制的本地诊断用于后续定位。
