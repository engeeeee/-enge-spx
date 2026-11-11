# 可选联合退出：审计与实施方案

基线为 0.12.0，主分支 `221f59f`。本批先完成退出设置和可验证的正常关闭，实机长期负载与性能验收继续沿用 [实机记录](field-recording.zh-CN.md)，不把夹具当作真实 Docker Desktop 验收。

## 现有行为与缺口

- `Engine.shutdown()` 已撤销授权、停止归属容器、等待后台锁并验证停止；保留这个只作用于本实例的接口，不能使预算变更或身份切换关闭全局 Desktop。
- `Controller.request_exit/finish_exit_when_quiet` 已排队退出、等待数据迁移和资源记录保存。联合关闭只能接在这之后，不能与采样或写入重叠。
- 设置、托盘和 Ctrl+Q 共用真正退出流程；X 隐藏及显式保留工作区不应触发全局停止。旧配置不启用新行为。

## 文件级方案

| 文件 | 改动与风险 |
| --- | --- |
| `desktop_shutdown.py` | 非敏感 schema=1 退出偏好；Windows 官方 Desktop CLI 的有界正常关闭与状态确认。无 force、kill、WSL 全局关闭或新依赖。状态/权限/超时失败不声称成功。中风险 |
| `ui/controller.py` | 独立保存偏好、捕获已保存选择、工作区和采样收尾后异步关闭 Desktop，失败保留界面并可重试。退出顺序与迁移接管是高风险测试点 |
| `ui/window.py` | 设置中提供默认未选中的开关与保存按钮，说明会影响其它 Docker 容器；真实退出菜单反映选择。低风险 |
| `tests/test_desktop_shutdown.py`、退出/记录测试 | 状态解析、默认兼容、保存权限、正常/已停止/旧版本/超时、退出顺序、保留工作区、失败重试与记录保存 |
| `tests/desktop_harness.py`、`test_gui_startup.py` | 原生 Windows 独立进程模拟管理接口，源码与冻结 GUI 验证 X 不停止、Ctrl+Q 正常关闭、默认不调用关闭接口。夹具不操作真实 Desktop |
| 退出指南、README、SECURITY、CHANGELOG、版本与 CI | 记录操作、影响范围、回滚与实际结果，保持同次完整发布门禁 |

偏好单独保存，不修改代理、身份或镜像配方；缺失时关闭，旧版本忽略文件。取消选项并保存即可恢复原退出方式。只在用户设置了联合退出且 Windows 真正停止并退出时管理本机 Docker Desktop；Docker 的其他工作负载属于该全局选择的影响范围，不逐个删除其容器或数据卷。

采用 [Docker Desktop stop](https://docs.docker.com/reference/cli/docker/desktop/stop/) 的同步正常关闭及 [status JSON](https://docs.docker.com/reference/cli/docker/desktop/status/)；不使用 `--force`，不以连接失败代替停止证明。旧 Desktop 不支持管理接口时保留窗口，用户可取消联合退出后只退出工作台。
