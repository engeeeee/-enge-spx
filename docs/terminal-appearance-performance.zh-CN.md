# 终端外观、编辑与性能

0.14.4 为 ENGE SPX 智能终端增加可保存的外观设置，并优化绘制和 Codex 草稿编辑。第三方终端继续使用自己的外观及快捷键设置。

**当前0.14.5修复0.14.4在Acrylic下标题栏透明穿透、拖动停滞及全屏滚动半帧闪烁的问题。** 下方0.14.4静态数字作为历史记录保留，不能代替全屏滚动验收。

## 自定义并保存

打开智能终端右上角 **⋯**：

- 背景效果：纯色或 Windows Acrylic 毛玻璃。
- 背景配色：暖灰、紫晶、石墨。
- 背景不透明度：30–100%，建议55–70%，只影响背景，文字保持不透明。新偏好默认65%；已保存的数值保留。
- 等宽字体及8–24 pt字号；原有 Ctrl+滚轮、Ctrl++/− 继续可用。
- 拖选后自动复制、右键直接粘贴。

偏好在当前应用数据目录的 `terminal-preferences.json` 自动保存，关闭窗口也会提交最后一次修改。再次打开终端会恢复。多个窗口分别保存修改的字段；现有窗口不会被强行同步或重启。失败会在状态栏提示，原配置保留。恢复默认前会保存一份旧配置，文件不包含提示词、图片、剪贴板或账号资料。

第一次由纯色启用 Acrylic，在**下次打开终端**时生效，避免切换原生窗口透明属性影响当前 CLI。Windows 11 22H2+ 优先使用系统 Desktop Acrylic；较旧的 Windows 10/11 尝试兼容接口，系统关闭透明效果、高对比度或接口不支持时使用不透明背景。兼容接口不是微软稳定的公开契约，因此不能承诺所有系统版本的视觉一致性。关闭毛玻璃不会让文字一起变透明。没有增加网页引擎、常驻服务或依赖。

## 输入与选择

右键只粘贴至草稿，不自动发送。Shift+右键也不会打开选项；菜单键和 Shift+F10 不再在命令行区域弹菜单，操作选项统一放在右上角。

Codex 原生鼠标启用后，字符左右半格分别对应前后插入点；中文和 emoji 按完整字符宽度定位，组合音标不拆分。点击与拖动继续通过 CLI 已协商的鼠标协议，未使用全局键盘钩子或外部窗口坐标。

在就绪的 Codex 输入区，Ctrl+A 选择草稿，Delete/Backspace 清空；左键拖选输入文字后 Delete/Backspace 删除原生选区，松开鼠标仍可自动复制。Ctrl+Shift+A 选择终端输出历史，仅供复制，不能删除。Shift+拖选也只选择输出。普通 Ctrl+C 中断规则保持不变。

全选删除是 Codex 适配：在确认存在草稿后使用其原生清空操作，不发送 Enter，不清空终端会话。已在 Codex 0.167.0 和0.169.0默认编辑模式回归；自定义键位、Vim模式及未来版本不能据此视为已验证。Claude 的 Ctrl+A 继续交给 Claude。可见选择高亮来自终端快照，长草稿被 CLI 折叠/滚动隐藏的部分不保证完整显示；清空操作由 CLI 处理完整草稿。

## 绘制性能证据

`terminal_paint.py` 缓存有界的行布局及静态文字，合并相同样式 ASCII 绘制，中文/emoji 保持网格定位。输出按时间预算分批解析，只更新脏行和光标区域；每轮排空之间让出事件循环。输入、协议回复、图片确认和 EOF 均保留原顺序，不丢输出。安全心跳与网络检查没有降低。

[Windows 对比运行](https://github.com/engeeeee/ENGE-SPX/actions/runs/43575988169)：Windows AMD64、Python3.12.10、Qt6.12.0、Cascadia Mono、DPR1，实际可用窗口1028×749、109×36格，每项40帧，同机比较0.14.3和本版实现。

| 合成操作 | 0.14.3 中位数 / P95 | 优化实现 中位数 / P95 |
| --- | --- | --- |
| 静态网格重绘 | 38.035 / 39.189 ms | 4.538 / 4.853 ms |
| 单行编辑后整窗绘制 | 38.576 / 39.279 ms | 5.092 / 5.739 ms |
| 全屏解析加绘制 | 51.893 / 54.117 ms | 19.291 / 20.047 ms |

这是合成 QWidget 绘制耗时，**不是实体显示器帧率、AI响应速度、整机CPU/内存或所有用户机器的提升保证**。不同运行负载的绝对值会变化。毛玻璃可能增加桌面合成开销；低资源场景可选择纯色。实体 Windows 10/11 的视觉与高刷新率手感仍需实机验收。

复现（两个实现使用同一环境、字体、可用窗口）：

```bash
python tools/benchmark_terminal.py --source /path/to/0.14.3/src --frames 40 --output before.json
python tools/benchmark_terminal.py --frames 40 --output after.json
```

## 0.14.5：拖动、材质与完整帧

0.14.4的实际Windows截图显示，标题栏空白像素alpha为零。分层窗口会让这些像素的鼠标穿透；只向窗口发送命中测试消息无法发现这一点。0.14.5显式启用标题栏背景绘制，并在自有HWND处理标题栏与边缘命中、最大化客户区。窗口按钮和命令行区域保持各自输入行为。

进入Windows移动／缩放循环前暂停Acrylic、使用不透明背景，退出后恢复，不改变偏好或CLI。效果切换只在状态变化时执行，不在每次移动或设置开关时重复初始化。去除兼容接口里第二层80%深色遮罩，使用深色系统材质和统一的标题栏／内容色调，防止颜色被重复压暗。实际质感仍受Windows主题、透明效果设置和桌面背景影响。

真实Codex0.169.0的合成会话记录到280组同步更新边界。旧版没有尊重这些边界，清屏和绘制分包时可能显示中间状态。新实现识别DEC2026及查询，保留最新完整帧；即使同一读取开始下一帧，也可显示上一张刚完成的画面。光标、曝光、选择重绘都从已提交位图绘制，不直接暴露正在修改的VT缓冲。未结束的同步更新150ms后恢复，协议和输出队列仍有界。

| 文件 | 实现 |
| --- | --- |
| `smart_terminal.py` | 完整帧捕获与提交、局部更新、原生窗口交互、幂等网格调整 |
| `terminal_render.py` | 同步更新／查询与分包解析，保留原OSC限制 |
| `terminal_paint.py` | 行位图复用，LRU最多128行、64MiB，不缓存整个对话的位图 |
| `window_effects.py` | 自有窗口的材质、命中坐标和最大化客户区 |
| `terminal_preferences.py` | 原schema1偏好兼容，范围扩展与默认值 |

当前帧位图按实际物理像素分配，1920×1080约7.91MiB；另有行缓存、Qt／系统合成缓冲及解析状态，不能视为终端总内存。普通行内文字批量更新并复用字形属性，复杂换行、插入、字符集、零宽组合等回到原解析器；500组固定种子的混合VT操作对原pyte逐格比较一致。无新依赖、线程监听或网络行为。

复现窗口检查（一次性Windows测试桌面，不读取剪贴板、不操作其它窗口）：

```powershell
python tools/probe_windows_terminal_window.py --output native-window.json
python tools/probe_windows_terminal_window.py --legacy-accent --output accent-window.json
$env:QT_SCALE_FACTOR = '1.5'
python tools/probe_windows_terminal_window.py --output native-dpi150.json
Remove-Item Env:QT_SCALE_FACTOR
```

检查包括实际HWND命中、标题栏非零像素、`WindowFromPoint`选中自己的窗口、按钮／边缘、最大化、移动循环效果暂停和恢复、输入不丢及HWND不替换。兼容Accent接口在CI实际Windows构建上强制选用，不能记为Windows10实体鼠标拖动通过。PNG来自运行的合成测试窗口，`QWidget.grab()`不包含完整桌面DWM材质，不能把它当作实机毛玻璃观感证据。

滚动测试显式分配1920×1080的离屏子视口，避免CI桌面将顶层窗口缩成1028×749：

```bash
python tools/probe_terminal_scroll.py --source /path/to/0.14.4/src --output before.json --frames 30
python tools/probe_terminal_scroll.py --output after.json --frames 30
PYTHONPATH=src python -m unittest discover -s tests -p 'test_terminal*.py' -v
```

记录解析加提交的中位数／P95、分包期间的半帧次数、最终像素一致性及缓存字节数。新实现要求半帧次数为零；合成视口不是物理显示器帧率。Windows10实机鼠标拖动、真实触控板、高刷新率和最终材质观感仍需实测反馈；不以API成功代替这些体验检查。

依据：[Microsoft窗口命中](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-nchittest)、[进入移动循环](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-entersizemove)、[退出移动循环](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-exitsizemove)、[Qt样式背景属性](https://doc.qt.io/qt-6/qt.html#WidgetAttribute-enum)。没有并入其它终端的代码、字体或渲染器，许可不变。

## 工作区系统时区

重新打开 CLI 时，核对项目容器的 `TZ`、`/etc/timezone` 和 `/etc/localtime` TZif。旧项目通过固定两项的 Docker 归档更新公开时区配置，保留容器ID、可写层和原挂载；不会把洛杉矶时区数据写进 UTC 数据库。失败时拒绝启动新CLI，状态栏给出错误。

浏览器根文件系统保持只读。软件从可信基础镜像离线准备仅含公开时区配置的派生镜像，准备容器无网络、无项目/账号挂载、无新增能力；实际浏览器仍为UID1000，原Profile及下载卷继续使用。镜像按基础镜像和时区缓存，不在每次打开时重建。无需重新下载运行环境。

已经打开的旧CLI进程不会热修改。升级后关闭旧终端，使用原数据目录重新打开。**网络控制容器与项目/浏览器只共享网络命名空间，文件系统独立**；旧控制容器的UTC系统文件不在本次在线迁移范围，诊断会分别展示，不能把控制容器文件当作项目文件。

实测及复现：`python tools/probe_workspace_timezone.py /tmp/timezone-probe.json` 创建和清理一次性Docker夹具，不使用账号。真实保护工作区的集成另核对项目和浏览器时区、原Profile、沙箱及挂载。

## 回滚

外观偏好为独立schema1文件；旧版忽略它，不迁移代理/账号配置。停止工作区并关闭终端后可换回旧程序。需要恢复UTC时，应先在应用里选择UTC并重新打开新版工作区，再回滚；不要手动改写zoneinfo数据库。时区派生镜像仅含公开文件，不提交、导出或复制用户项目/账号数据。

若回滚到0.14.4，先将背景不透明度调回55–100%；0.14.4不接受新增的30–54%范围。0.14.5会保留并读取旧版本全部合法偏好，不改变账号或代理格式。
