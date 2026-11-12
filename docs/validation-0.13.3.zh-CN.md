# 0.13.3 Docker 后台已退出时的收尾修复

## 问题与范围

0.13.2 已处理管理接口明确返回 stopped 的手动退出顺序。实际反馈暴露另一条路径：连 Desktop 后台及管理接口也退出后，Linux 引擎管道和状态 API 一起消失，原逻辑无法获得 stopped，重新抛出缺失管道错误并保留界面。本批只补充这一离线证据路径，保留原退出机制及账号、代理、身份、预算、镜像和许可。

## 文件与方案

- `src/enge_spx/desktop_offline.py`：只读检查 WSL2 设置、严格进程快照、固定本机管道和 WSL 注册/运行列表，重复检查进程及管道；不输出原始命令结果或用户发行版名称。
- `desktop_shutdown.py`：管理状态不可用时，只允许精确本机 Desktop Linux context 使用独立证据；联合关闭的状态确认也使用此路径，沿用总时限。
- `process_metrics.py`：为停止证据增加严格枚举，失败/部分列表不能视为空；资源显示保留默认宽容模式。
- `tests/test_desktop_offline.py`、`test_desktop_shutdown.py`、`test_exit_lifecycle.py`：覆盖接口消失、权限/编码/超时、仍运行、重启、未知/不匹配上下文、凭据清理与数据保留；Windows 门禁实际调用 Win32 私有测试管道和进程快照。
- 版本、打包元数据、CI 资产与本次文档同步为 0.13.3。无配置格式或生产依赖变更；回滚无需逆迁移。

管理状态明确 running / starting / stopping / paused 时，不用离线证据覆盖它。单独管道缺失或仅无前台窗口始终不足。独立路径要求设置明确为 WSL2，不能用于 Hyper-V 或未知后端。其它运行中的 WSL 发行版不被停止。Engine 仍先撤销授权、等待本实例 guard/forward/relay，然后重新核验。

依据为 [Docker status JSON 接口](https://docs.docker.com/reference/cli/docker/desktop/status/)、[WSL 列表命令](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)、[Microsoft WSL 列表实现](https://github.com/microsoft/WSL/blob/master/src/windows/common/WslClient.cpp)、[Win32 管道等待](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-waitnamedpipew)及 [进程枚举结束状态](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-process32nextw)。源码不复制第三方实现。

## 本地验证

原版函数与候选函数在相同的“管理接口失败、独立证据满足”输入下，分别返回 False / True，复现并覆盖缺失分支。

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_desktop*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_exit*.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/check_repository.py
node --test tests/test_release_publication.cjs
```

Linux ARM64 专项：Desktop 34 项（32 通过、2 项 Win32 专用跳过）；退出 34 项通过。完整本地回归 401 项：386 通过、15 项 Windows 专用跳过，用时约 11.6 秒；9 项发布助手测试、Qt smoke 和 70 篇文档/版本元数据检查通过。Windows、冻结包及发布门禁在执行完成后补充，未执行/跳过不记为通过。独立 WSL 状态组合使用注入结果，不能冒充在用户 Docker Desktop 4.99.0 / WSL2 设备上实际验收。

## 性能与边界

无常驻进程、轮询、监听端口或新增运行依赖；正常运行与管理接口可用时不进入新增 WSL 查询。失败路径每次独立证据最多两次只读 WSL 列表，单条子命令最多 3 秒，证据预算最多 8 秒，联合退出继续受原总时限约束；Engine 收尾后的复核重新取证。没有测量用户设备退出耗时或持续 CPU/内存变化，不声称提升百分比。

真实设备反馈尚待用户升级后确认；暂不处理既有终端偶发拒绝访问。保持未知状态可重试，不用不安全的跳过核验替代本修复。
