import argparse
import json
from pathlib import Path
import subprocess
import sys

from . import __version__
from .engine import Engine
from .nodes import fetch_subscription, parse_nodes
from .state import Store, SPXError


def main():
    parser = argparse.ArgumentParser(prog="spx", description="ENGE SPX — 本机项目、共享工具与受控代理出口")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data", type=Path, help="专用数据目录；默认跟随偏好设置中的迁移位置")
    parser.add_argument("--project", default=str(Path.cwd()), help="项目目录")
    parser.add_argument("--smoke-gui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="action")
    for action in ("gui", "doctor", "diagnostics", "check", "confirm", "browser", "stop", "status", "guard", "relay", "forward", "shell"):
        sub.add_parser(action)
    installer = sub.add_parser("install")
    installer.add_argument("--from-source", action="store_true", help="从源码构建，不下载预构建环境")
    starter = sub.add_parser("start", help="自动准备 Docker、运行环境和连接检查，等待出口确认")
    starter.add_argument("--no-install", action="store_true", help="不下载缺失的运行环境")
    starter.add_argument("--no-start-docker", action="store_true", help="只使用已运行的 Docker，不自动唤起 Desktop")
    importer = sub.add_parser("import-node")
    importer.add_argument("file", type=Path, help="本地订阅/节点文件（不保存订阅地址）")
    selector = sub.add_parser("select")
    selector.add_argument("index", type=int, help="节点序号，从 1 开始")
    for action in ("claude", "codex", "exec"):
        item = sub.add_parser(action, add_help=False)
        item.add_argument("arguments", nargs=argparse.REMAINDER)
    args, forwarded = parser.parse_known_args()
    if forwarded and args.action not in ("claude", "codex", "exec"):
        parser.error("unrecognized arguments: " + " ".join(forwarded))
    try:
        if args.self_test:
            from .downloads import client
            from .forward import tunnel_type
            from .platform_ui import ASSETS
            for proxy in ("http://127.0.0.1:9", "socks5://127.0.0.1:9"):
                with client(proxy):
                    pass
            assert tunnel_type() and (ASSETS / "app.ico").is_file()
            print(json.dumps({"app": "ENGE SPX", "version": __version__, "python": sys.version.split()[0], "resources": True, "proxy_transports": True}))
            return 0
        store = Store(args.data)
        if args.action in (None, "gui"):
            try:
                from .gui import launch
            except ImportError as error:
                raise SPXError("桌面界面依赖不完整，请安装 requirements.txt 后重试。") from error
            launch(store, smoke=args.smoke_gui)
            return 0
        engine = Engine(store, lambda text: print(text, file=sys.stderr, flush=True))
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
            cmd = engine.tool_command(args.project, command, interactive=attached)
            return subprocess.call(cmd, env=engine.docker.environment())
        else:
            result = getattr(engine, args.action)()
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
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
