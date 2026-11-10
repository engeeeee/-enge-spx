# 0.8.4 启动热修复验证记录

日期：2026-11-10。基线为 0.8.3，`254f37832da66f674ff0939bf8e84a8055f92479`。第二批协议开发暂停，其改动保留在独立分支，不进入本次热修复。

## 修改与原因

旧浏览器要到 `_browser()` 才移除，但在此前的 `confirm()` 中 `audit_topology()` 已遍历全部本实例容器，检查停止的旧浏览器是否满足新 seccomp/只读根文件系统条件。这使旧数据用户无法走到更换浏览器的步骤。修复前在当前与 legacy 两种命名下均重现；调整清理顺序后同一测试可以完成 check → confirm，项目容器保留。

Docker 安全选项存在等效的 `=` / `:` 表示。原校验只接受部分形式；新解析器在第一个分隔符切开，保留重复项用于冲突检查，不降低安全要求。失败只报告固定检查项，方便区分真正缺失权限边界与表示格式问题。

## 文件和边界

- `src/enge_spx/engine.py`：在停止环境后、出口检查前清理本实例已停止的浏览器，复用 `_browser()` 原有的安全替换逻辑。不强制删除、不删除卷，不放行运行中的不安全浏览器。
- `src/enge_spx/browser_security.py`：安全选项兼容解析与脱敏失败字段；继续逐项检查 UID、capabilities、只读根、no-new-privileges 与专用策略，并验证真实 renderer。
- `tests/test_migration.py`、`tests/test_security_p0.py`、`tests/integration_runtime.py`：升级确认、数据保留、安全选项与危险配置回归。
- 版本元数据、打包 CI、README 中英文、CHANGELOG、P0 升级说明与本记录：0.8.4 发布和恢复说明。

无新增依赖、监听端口、持久后台进程或凭据格式迁移。网关/工作/浏览器镜像配方不变；配置、DPAPI 封套和数据卷保持兼容。项目许可证及第三方声明不变。

## 测试命令与结果

本地 Linux ARM64 / Python 3.14：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/check_repository.py
```

单元测试发现 176 项，166 通过、10 项 Windows 专属检查跳过，无失败。Windows 原生与真实 Docker 项目由同版本 CI 单独执行，不将跳过的测试算作实测通过。

CI 的 Python 3.12 / Windows、Linux，以及原生 Linux Docker：

```bash
python tools/check_repository.py
python -m unittest discover -s tests -v
python -u tests/integration_runtime.py --context default --output integration-results.json
python -u tests/integration_chain.py --context default
python tests/integration_prebuilt.py --context default --directory RUNTIME_PACKAGE
python tools/check_frozen_credentials.py dist/ENGE-SPX/spx.exe
```

CI 门禁还包括 Windows GUI、DPI、冻结程序手动 Docker 启动、安装卸载，以及归档在两种 Docker 镜像存储中的导入。发布必须等待同次 CI 的安装包与容器任务通过；实际执行结果以该提交的 Actions 记录为准。

新增真实 Docker 用例使用当前工作镜像创建一个无网络、没有新沙箱配置的旧浏览器替身，只写资料和下载标记，不运行过时的无沙箱浏览器。检查后该实例被移除；新浏览器必须通过完整 renderer 验证并读取原卷中的两个标记。`=` / `:` 两种 no-new-privileges 创建方式还要求 PID 1 实际报告 `NoNewPrivs=1`。

## 性能与剩余限制

本次修复没有更换 Chromium、网关、VNC、资源限制、检测周期或镜像配方。停止浏览器的删除操作从打开工具前提前到出口检查前；不增加持续轮询或常驻进程。没有在同一 Windows / WSL2 主机开展 CPU、内存、吞吐或完整启动时间对比，不声称性能提升。

用户报告 Docker Desktop 4.99.0（245822），查到 legacy 命名的已停止浏览器；手动移除该停止实例后，用户确认 0.8.3 可以正常工作，与源码重现的升级阻塞一致。0.8.4 自动执行这一步，无需用户命令。原始容器的完整安全字段未作为自动化证据采集。CI 的原生 Linux Docker 与 Windows GUI/DPAPI 不等价于这台机器的 Docker Desktop / WSL2 沙箱验收。新安装包仍需在该机器复测；若失败，新错误会给出具体检查项，不使用扩大权限或无沙箱方式绕过。

下一步先完成用户机器的启动复测；第二批代理适配、Reality、QUIC 与防泄漏工作待用户恢复后继续。
