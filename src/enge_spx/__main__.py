import argparse
import json
from pathlib import Path
import subprocess
import sys

from . import __version__
from .engine import Engine
from .nodes import fetch_subscription, parse_nodes
from .state import Store, SPXError


def record_number(value):
    try:
        return int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("记录时长和间隔需填写整数。") from error


def main():
    # Frozen Windows CLI pipes may use a non-CJK code page. Keep machine JSON
    # ASCII-escaped and human error messages printable instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(prog="spx", description="ENGE SPX — 本机项目、共享工具与受控代理出口")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data", type=Path, help="专用数据目录；默认跟随偏好设置中的迁移位置")
    parser.add_argument("--project", default=str(Path.cwd()), help="项目目录")
    parser.add_argument("--without-browser", action="store_true", help="显式仅运行 CLI，不启动浏览器；不会回退到本机或无沙箱浏览器")
    parser.add_argument("--smoke-gui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--terminal-preview", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="action")
    for action in ("gui", "doctor", "diagnostics", "check", "confirm", "browser", "stop", "status", "guard", "relay", "forward", "shell"):
        sub.add_parser(action)
    sub.add_parser("stop-browser", help="停止浏览器及显示服务，保留 CLI、网关和持久资料")
    identities = sub.add_parser("profiles", help="独立账号/浏览器身份及项目只读授权；切换会停止工作区")
    identity_actions = identities.add_subparsers(dest="profile_action", required=True)
    identity_actions.add_parser("list", help="查看身份和项目授权，不启动 Docker")
    create_identity = identity_actions.add_parser("create", help="创建空白身份，不复制现有账号，也不自动切换")
    create_identity.add_argument("name")
    select_identity = identity_actions.add_parser("select", help="停止工作区并切换浏览器身份；不改变项目绑定")
    select_identity.add_argument("identity")
    apply_identity = identity_actions.add_parser("apply", help="将 --project 项目绑定到身份并显式设置权限")
    apply_identity.add_argument("identity")
    apply_identity.add_argument("--access", choices=("ro", "rw"), required=True)
    identity_actions.add_parser("restore", help="恢复上次选择/授权，保留所有身份数据")
    network = sub.add_parser("network-check", help="主动检查当前受控工作区并生成脱敏网络证据；不启动 Docker 或浏览器")
    network.add_argument("--skip-browser", action="store_true", help="不执行实际浏览器语言/时区/WebRTC 检查")
    network.add_argument("--output", type=Path, help="导出脱敏 JSON，不含代理凭据、项目路径或浏览器令牌")
    network_test = sub.add_parser("network-test", help="主动测量最终受控链路的 HTTPS 耗时与约 1 MiB 下载；不启动 Docker，不测上传")
    network_test.add_argument("--output", type=Path, help="保存脱敏测速报告；固定访问 Cloudflare，不上传报告")
    resources = sub.add_parser("resources", help="只读资源采样，或停止工作区后保存/恢复预算")
    resource_action = resources.add_mutually_exclusive_group()
    resource_action.add_argument("--apply", type=Path, help="保存 schema=1 JSON 预算；会停止本工作区，下次启动应用")
    resource_action.add_argument("--restore", action="store_true", help="恢复上次预算，会停止本工作区")
    resource_action.add_argument("--show-settings", action="store_true", help="输出有效预算，不启动 Docker")
    resource_action.add_argument("--record", type=Path, help="显式记录真实使用期间的资源占用到脱敏 JSON；不启动 Docker，Ctrl+C 保存已采集结果")
    resources.add_argument("--seconds", type=record_number, default=900, help="记录时长 5–3600 秒，默认 900")
    resources.add_argument("--interval", type=record_number, default=10, help="记录的最短间隔 5–60 秒，查询耗时单独计入")
    resources.add_argument("--activity", default="unspecified", help="活动标签：unspecified/gui_idle/workspace_idle/claude/codex/browser/stopped；不读取 AI 输入或账号")
    resources.add_argument("--docker-context", help="显式选择本机 Docker 上下文；缺省使用已核验的公开记录，不读取代理设置")
    installer = sub.add_parser("install")
    installer.add_argument("--from-source", action="store_true", help="从源码构建，不下载预构建环境")
    starter = sub.add_parser("start", help="自动准备 Docker、运行环境和连接检查，等待出口确认")
    starter.add_argument("--no-install", action="store_true", help="不下载缺失的运行环境")
    starter.add_argument("--no-start-docker", action="store_true", help="只使用已运行的 Docker，不自动唤起 Desktop")
    importer = sub.add_parser("import-node")
    importer.add_argument("file", type=Path, help="本地订阅/节点文件（不保存订阅地址）")
    selector = sub.add_parser("select")
    selector.add_argument("index", type=int, help="节点序号，从 1 开始")
    attach = sub.add_parser("attach", help=argparse.SUPPRESS)
    attach.add_argument("tool", choices=("claude", "codex", "shell", "login-claude", "login-codex"))
    attach.add_argument("--session", required=True)
    attach.add_argument("--container", required=True)
    attach.add_argument("--smart-terminal", action="store_true", help=argparse.SUPPRESS)
    credentials = sub.add_parser("credentials", help="凭据保护、迁移、删除和显式旧格式导出")
    credentials.add_argument("operation", choices=("status", "migrate", "clear-proxies", "export-legacy"))
    credentials.add_argument("--output", type=Path)
    credentials.add_argument("--allow-plaintext", action="store_true")
    for action in ("claude", "codex", "exec"):
        item = sub.add_parser(action, add_help=False)
        item.add_argument("arguments", nargs=argparse.REMAINDER)
    args, forwarded = parser.parse_known_args()
    if forwarded and args.action not in ("claude", "codex", "exec"):
        if args.action == "network-test":
            parser.error("network-test 不接受自定义目标、代理或其它参数；仅支持 --output。")
        parser.error("unrecognized arguments: " + " ".join(forwarded))
    resource_query = args.action == "resources" and not (args.apply or args.restore or args.show_settings)
    try:
        if args.terminal_preview:
            from .smart_terminal import preview
            return preview()
        if args.self_test:
            from .smart_terminal import TerminalScreen
            assert TerminalScreen(80, 24).columns == 80
            from .downloads import client
            from .forward import tunnel_type
            from .platform_ui import ASSETS
            from .brand import PACKAGE_RESOURCES
            from .credentials import CredentialCodec
            from .desktop_settings import resolve as resolve_desktop_backend
            implicit = resolve_desktop_backend({})
            assert implicit.enabled and implicit.implicit
            assert not resolve_desktop_backend({"wslEngineEnabled": False}).enabled
            for proxy in ("http://127.0.0.1:9", "socks5://127.0.0.1:9"):
                with client(proxy):
                    pass
            assert tunnel_type() and (ASSETS / "app.ico").is_file() and (PACKAGE_RESOURCES / "checks/exit_probe.py").is_file()
            for name in ("browser-seccomp.json", "sandbox_status.py", "runtime_secret.py"):
                assert (PACKAGE_RESOURCES / "containers" / name).is_file()
            for name in ("environment_probe.py", "browser_probe.py", "browser_shutdown.py", "network_probe.py", "clipboard_transfer.py"):
                assert (PACKAGE_RESOURCES / "checks" / name).is_file()
            codec = CredentialCodec("000000000000")
            fixture = [{"password": "synthetic-self-test-only"}]
            assert codec.decode("nodes.json", codec.encode("nodes.json", fixture)) == fixture
            print(json.dumps({"app": "ENGE SPX", "version": __version__, "python": sys.version.split()[0], "resources": True, "proxy_transports": True, "credential_protection": "dpapi-current-user" if codec.enabled else "private-files"}))
            return 0
        store = Store(args.data)
        # Internal children may be started while the parent holds the operation
        # lock (notably the display relay). Their Store still encrypts every new
        # secret write, but they must not wait for a second migration lock.
        if not resource_query and args.action not in ("stop", "credentials", "guard", "relay", "forward", "attach"):
            store.migrate_credentials()
        if args.action in (None, "gui"):
            try:
                from .gui import launch
            except ImportError as error:
                raise SPXError("桌面界面依赖不完整，请安装 requirements.txt 后重试。") from error
            launch(store, smoke=args.smoke_gui)
            return 0
        try:
            if resource_query:
                from .resource_monitor import sampling_target
                engine = sampling_target(store, args.docker_context)
            else:
                engine = Engine(store, lambda text: print(text, file=sys.stderr, flush=True))
        except SPXError:
            if args.action != "stop":
                raise
            context = store.read("controller-context.json", {})
            if context.get("instance") != store.instance or not context.get("context"):
                raise
            engine = Engine(store, lambda text: print(text, file=sys.stderr, flush=True), stop_context=context["context"])
            engine.doctor()
        if args.action == "relay":
            from .relay import main as relay_main
            relay_main(store)
            return 0
        elif args.action == "forward":
            from .forward import main as forward_main
            forward_main(store)
            return 0
        elif args.action == "diagnostics":
            from .startup import diagnostics
            result = diagnostics(store)
        elif args.action == "stop-browser":
            result = engine.stop_browser()
        elif args.action == "profiles":
            if args.profile_action == "list":
                result = engine.workspace_profiles()
            elif args.profile_action == "create":
                result = engine.create_workspace_profile(args.name)
            elif args.profile_action == "select":
                result = engine.configure_workspace(args.identity)
            elif args.profile_action == "apply":
                result = engine.configure_workspace(args.identity, args.project, args.access)
            else:
                result = engine.restore_workspace_profiles()
        elif args.action == "network-check":
            result = engine.network_diagnostics(browser=not args.skip_browser)
            if args.output:
                from .state import atomic_json
                atomic_json(args.output, result)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 2 if result.get("status") in ("unsafe", "failed") else 0
        elif args.action == "network-test":
            result = engine.network_performance()
            if args.output:
                from .state import atomic_json
                atomic_json(args.output, result)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result.get("status") in ("checked", "not_ready") else 2
        elif args.action == "resources":
            from .resource_limits import validate
            if args.apply:
                try:
                    with args.apply.open("r", encoding="utf-8-sig") as stream:
                        content = stream.read(512 * 1024 + 1)
                except UnicodeError as error:
                    raise SPXError("资源设置文件必须使用 UTF-8 JSON。") from error
                if len(content) > 512 * 1024:
                    raise SPXError("资源设置文件不能超过 512 KiB。")
                try:
                    config = json.loads(content)
                except ValueError as error:
                    raise SPXError("资源设置必须是有效的 schema=1 JSON。") from error
                result = engine.save_resources(config)
            elif args.restore:
                result = engine.restore_resources()
            elif args.show_settings:
                result = validate(store.settings().get("resources"))
            elif args.record:
                from .resource_monitor import Monitor
                from .resource_recording import record, settings as record_settings
                monitor = Monitor()
                config = record_settings(args.seconds, args.interval, args.activity)
                print(f"开始性能记录：最多 {args.seconds} 秒，查询之间至少间隔 {args.interval} 秒。Ctrl+C 会保存已采集结果。", file=sys.stderr, flush=True)
                result = record(lambda cancel: monitor.snapshot(engine, docker_ready=engine.ready and bool(engine.docker.executable), cancel=cancel), output=args.record, **config, source="cli",
                                on_sample=lambda raw, count, elapsed: print(f"已记录 {count} 份采样 · {elapsed:.0f} 秒", file=sys.stderr, flush=True))
                print(json.dumps({key: result[key] for key in ("schema", "kind", "end_reason", "elapsed_seconds", "sample_count", "coverage", "summary")}, ensure_ascii=True, indent=2))
                return 130 if result["end_reason"] == "interrupted" else 0
            else:
                from .resource_monitor import Monitor
                result = Monitor().snapshot(engine, docker_ready=engine.ready and bool(engine.docker.executable))
        elif args.action == "credentials":
            if args.operation == "status":
                result = {"schema": 1, "mode": "dpapi-current-user" if store.credentials.enabled else "private-files", "pending": store.credentials.pending(store.home)}
            elif args.operation == "migrate":
                engine.stop()
                result = store.migrate_credentials()
            elif args.operation == "clear-proxies":
                engine.clear_proxy_credentials()
                result = {"proxy_credentials_cleared": True}
            else:
                if args.output is None or not args.allow_plaintext:
                    raise SPXError("请指定 --output 专用目录及 --allow-plaintext，导出会包含明文凭据。")
                engine.stop()
                result = store.export_legacy_credentials(args.output, args.allow_plaintext)
        elif args.action == "attach":
            if args.smart_terminal:
                from .smart_terminal import run as smart_attach
                return smart_attach(engine, args.project, args.tool, args.session, args.container)
            command = engine.attach_command(args.project, args.tool, args.session, args.container, interactive=bool(sys.stdin and sys.stdin.isatty()))
            return subprocess.call(command, env=engine.docker.environment())
        elif args.action == "start":
            from .startup import prepare_workspace
            result = prepare_workspace(engine, auto_start=not args.no_start_docker, install=not args.no_install, progress=lambda value: print(value.get("message", value["stage"]), file=sys.stderr, flush=True))
        elif args.action == "install":
            result = engine.install() if args.from_source else engine.install_prebuilt()
        elif args.action == "import-node":
            nodes, warnings = parse_nodes(args.file.read_text(encoding="utf-8-sig"))
            engine.save_nodes(nodes)
            result = {"nodes": [{"index": i + 1, "name": n["label"]} for i, n in enumerate(nodes)], "warnings": warnings}
        elif args.action == "select":
            nodes = store.read("nodes.json", [])
            if not 1 <= args.index <= len(nodes):
                raise SPXError("节点序号不存在。")
            settings = store.settings()
            engine.save_settings(nodes[args.index - 1]["id"], settings["timezone"], settings["context"])
            result = {"selected": nodes[args.index - 1]["label"]}
        elif args.action in ("claude", "codex", "exec", "shell"):
            tail = [*forwarded, *getattr(args, "arguments", [])]
            if tail[:1] == ["--"]:
                tail = tail[1:]
            command = [args.action, *tail] if args.action in ("claude", "codex") else ["bash", "-l"] if args.action == "shell" else tail
            if not command:
                raise SPXError("请在 exec 后填写 Linux 命令。")
            attached = bool(sys.stdin and sys.stdin.isatty())
            cmd = engine.tool_command(args.project, command, interactive=attached, browser=False if args.without_browser else None)
            return subprocess.call(cmd, env=engine.docker.environment())
        else:
            result = getattr(engine, args.action)()
        if result is not None:
            print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (SPXError, OSError) as error:
        if sys.stderr:
            print(str(error), file=sys.stderr)
        elif args.action in (None, "gui"):
            import ctypes
            user = ctypes.WinDLL("user32")
            user.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            user.MessageBoxW(None, str(error), "无法打开 ENGE SPX", 0x10)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
