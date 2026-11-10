from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
import queue
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .state import Store, SPXError, fingerprint, status_snapshot
from .brand import CONTAINERS, LEGACY_LABEL_ROOT, PACKAGE_RESOURCES
from .compat import LEGACY_RECIPES, LEGACY_RUNTIME_DIRECTORY, LEGACY_BROWSER_TOKEN
from .docker_env import environment as docker_environment
from .line_security import LineSecurityError
from .startup import DockerUnavailable, DockerContextUnavailable, DockerConfigurationError
from .backends import DEFAULT_BACKEND, get_backend

OWNER = "io.enge.spx.instance"
ROLE = "io.enge.spx.role"
STORAGE = "io.enge.spx.storage"
RECIPE = "io.enge.spx.recipe"
GATEWAY_IMAGE = DEFAULT_BACKEND.image
RESOURCES = CONTAINERS
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
TOOLS = {"claude": ["claude"], "codex": ["codex"], "shell": ["bash", "-l"], "login-claude": ["claude", "auth", "login"], "login-codex": ["codex", "login"]}


def image_recipe(image):
    labels = image.get("Config", {}).get("Labels") or {}
    return labels.get(RECIPE, labels.get(LEGACY_LABEL_ROOT + ".recipe"))


class Docker:
    @staticmethod
    def desktop_app(executable=None):
        from .docker_env import desktop_application
        return desktop_application(executable)

    def __init__(self, context: str):
        self.secret_env = {}
        self.redact = lambda value: str(value)
        candidates = [shutil.which("docker")]
        if os.name == "nt":
            candidates += [str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe")]
            candidates += [str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe")]
        self.executable = next((x for x in candidates if x and Path(x).is_file()), None)
        if not self.executable and os.name == "nt":
            application = self.desktop_app()
            candidate = application.parent / "resources/bin/docker.exe" if application else None
            if candidate and candidate.is_file():
                self.executable = str(candidate)
        self.context = context

    def command(self, *args) -> list[str]:
        if not self.executable:
            raise SPXError("未找到 Docker Desktop，请安装并启动 Docker Desktop，切换到 Linux containers。")
        return [self.executable, "--context", self.context, *map(str, args)]

    def environment(self):
        # A desktop shortcut can inherit PATH from before Docker was installed.
        # The absolute CLI path alone does not make its credential helpers visible.
        return {**docker_environment(self.executable), **self.secret_env}

    def run(self, *args, timeout=60, log: Path | None = None, on_line=None, cancel=None, input_data=None) -> str:
        try:
            if log:
                with log.open("a", encoding="utf-8") as stream:
                    process = subprocess.Popen(self.command(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=self.environment(), creationflags=HIDDEN)
                    lines = queue.Queue()
                    def read():
                        for line in process.stdout:
                            lines.put(line)
                        lines.put(None)
                    threading.Thread(target=read, daemon=True).start()
                    deadline = time.monotonic() + timeout
                    try:
                        while True:
                            if cancel and cancel.is_set():
                                from .downloads import DownloadPaused
                                raise DownloadPaused("操作已取消，已有下载和构建缓存会保留。")
                            if time.monotonic() > deadline:
                                raise subprocess.TimeoutExpired(self.command(*args), timeout)
                            try:
                                line = lines.get(timeout=.15)
                            except queue.Empty:
                                continue
                            if line is None:
                                break
                            line = self.redact(line)
                            stream.write(line)
                            stream.flush()
                            if on_line:
                                on_line(line.rstrip())
                        code = process.wait(timeout=5)
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                        process.stdout.close()
                    result = subprocess.CompletedProcess(self.command(*args), code)
                output, error = "", f"详细日志：{log}"
            else:
                result = subprocess.run(self.command(*args), input=input_data, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=self.environment(), creationflags=HIDDEN)
                output, error = result.stdout, result.stderr.strip()[-1500:]
        except subprocess.TimeoutExpired as error:
            raise SPXError("Docker 操作超时，请检查 Docker Desktop 状态及运行日志。") from error
        except OSError as error:
            raise SPXError("Docker 无法启动，请检查 Docker Desktop 安装。") from error
        if result.returncode:
            raise SPXError("Docker 机密输入操作失败，输入和原始错误输出未记录。" if input_data is not None else "Docker 操作失败：" + self.redact(error))
        if not log and args[:1] == ("logs",):
            # Docker puts the container's stderr on its own stderr even on a
            # successful `logs` call. Keep that diagnostic path redacted too.
            return self.redact(output + result.stderr).strip()
        return output.strip()

    def inspect(self, kind: str, name: str):
        try:
            return json.loads(self.run(kind, "inspect", name))[0]
        except SPXError as error:
            if any(x in str(error).lower() for x in ("no such", "not found")):
                return None
            raise


class Engine:
    def __init__(self, store: Store, log=lambda message: None, stop_context=None):
        self.store, self.log = store, log
        self.settings = {"context": stop_context} if stop_context else store.settings()
        self.backend = get_backend(self.settings.get("proxy_backend"))
        self.docker = Docker(self.settings["context"])
        from .redaction import redact, values
        self.secret_values = set() if stop_context else values(self.settings) | values(store.read("nodes.json", [])) | values(store.read("runtime.json", {})) | values(store.read("relay.json", {}))
        self.docker.redact = lambda text: redact(text, self.secret_values)
        self.owner = LEGACY_LABEL_ROOT + ".instance" if store.legacy else OWNER
        self.role = LEGACY_LABEL_ROOT + ".role" if store.legacy else ROLE
        self.prefix = ("ewbw-" if store.legacy else "spx-") + store.instance
        self.internal, self.external = self.prefix + "-internal", self.prefix + "-external"
        files = {p.relative_to(RESOURCES).as_posix(): p.read_text(encoding="utf-8") for p in sorted(RESOURCES.rglob("*")) if p.is_file() and "__pycache__" not in str(p)}
        self.recipe = fingerprint(files)[:12]
        self.recipes = {role: fingerprint({name: files[name] for name in names})[:12] for role, names in {"gateway": ["Dockerfile.gateway", "gateway.py", "tunnel.py", "runtime_secret.py"], "work": ["Dockerfile.work", "probe.py", "open_browser.py"]}.items()}
        self.recipes["browser"] = fingerprint({"work": self.recipes["work"], **{name: files[name] for name in ("Dockerfile.browser", "browser.py", "vnc_stdio.py", "chromium-policy.json", "sandbox_status.py", "runtime_secret.py", "browser-seccomp.json")}})[:12]
        self.images = {role: "enge-spx/" + role + ":" + self.recipes[role] for role in ("gateway", "work", "browser")}
        self._image_abis = {}

    def compatible_image(self, image, role):
        if not image or role not in self.recipes:
            return False
        recipe = image_recipe(image)
        # Gateway and browser must upgrade to stdin credentials and the sandbox.
        # Work images keep their ABI and writable project layers intact.
        return recipe == self.recipes[role] or role == "work" and self.store.legacy and recipe == LEGACY_RECIPES[role]

    def runtime_path(self, role, filename):
        if role not in self._image_abis:
            self.image_ids()
        directory = LEGACY_RUNTIME_DIRECTORY if self._image_abis[role] == "legacy" else "/opt/spx"
        return directory + "/" + filename

    def owned(self, obj, role: str | None = None):
        labels = obj.get("Config", {}).get("Labels", obj.get("Labels")) or {}
        if labels.get(self.owner) != self.store.instance or (role and labels.get(self.role) != role):
            raise SPXError("资源归属不一致，已停止操作；未修改其他 Docker 资源。")
        return obj

    def inspect(self, role: str, name: str | None = None):
        obj = self.docker.inspect("container", name or self.prefix + "-" + role)
        return self.owned(obj, role) if obj else None

    def doctor(self, timeout=60) -> dict:
        if not self.docker.executable:
            raise DockerUnavailable("未找到 Docker Desktop 命令行工具。")
        try:
            raw = self.docker.run("context", "inspect", self.docker.context, timeout=timeout)
        except SPXError as error:
            raise DockerContextUnavailable("Docker 上下文尚不可用，请检查 Docker Desktop 是否已完成初始化。") from error
        try:
            contexts = json.loads(raw)
            if not isinstance(contexts, list) or len(contexts) != 1 or not isinstance(contexts[0], dict):
                raise ValueError()
            context = contexts[0]
            endpoint = context["Endpoints"]["docker"]["Host"]
            if not isinstance(endpoint, str):
                raise ValueError()
        except (ValueError, KeyError, TypeError) as error:
            raise DockerConfigurationError("Docker 上下文信息无效，请检查 Docker 安装和上下文设置。") from error
        if not endpoint.startswith(("npipe://", "unix://")):
            raise DockerConfigurationError("请选择本机 Docker Desktop 上下文；此版本不支持远程 Docker。")
        try:
            info = json.loads(self.docker.run("info", "--format", "{{json .}}", timeout=timeout))
            if not isinstance(info, dict) or not info.get("OSType"):
                raise ValueError()
        except (SPXError, ValueError, TypeError) as error:
            raise DockerUnavailable("Docker 引擎尚未就绪或连接被拒绝，请检查 Docker Desktop 窗口中的状态。") from error
        if info.get("OSType") != "linux":
            raise DockerConfigurationError("Docker 当前未使用 Linux containers，请在 Docker Desktop 中切换后重试。")
        try:
            supported = int(info.get("ServerVersion", "0").split(".")[0]) >= 28
        except (ValueError, TypeError, AttributeError):
            supported = False
        if not supported:
            raise DockerConfigurationError("需要 Docker Engine 28 或更新版本，请更新 Docker Desktop。")
        arch = info.get("Architecture", "")
        if arch not in ("x86_64", "amd64", "aarch64", "arm64"):
            raise DockerConfigurationError("仅支持 x64 或 ARM64 的 Linux 容器引擎。")
        return {"docker": info.get("ServerVersion"), "architecture": arch, "context": self.docker.context, "data": str(self.store.home)}

    def install(self, progress=None, cancel=None):
        with self.store.lock():
            self.doctor()
            self.networks()
            build_log = self.store.home / "build.log"
            installed = {}
            saved = self.store.read("images.json", {})
            for role in ("gateway", "work", "browser"):
                item = self.docker.inspect("image", saved.get(role, self.images[role]))
                if self.compatible_image(item, role):
                    installed[role] = item["Id"]
                    self.log(role + " 镜像已就绪。")
                    continue
                self.log("构建 " + role + " 镜像；首次安装需要下载工具和 Chromium…")
                if progress:
                    progress({"stage": "build", "role": role})
                work_reference = self.images["work"]
                if role == "browser":
                    base = self.docker.inspect("image", work_reference)
                    if not base or base["Id"] != installed["work"]:
                        # BuildKit FROM requires a named reference. A bare image
                        # ID is parsed as a registry repository; preserve the old
                        # image under an instance-scoped alias without moving tags.
                        work_reference = "enge-spx/build-base:" + self.store.instance + "-" + installed["work"].split(":")[-1][:12]
                        alias = self.docker.inspect("image", work_reference)
                        if alias and alias["Id"] != installed["work"]:
                            raise SPXError("构建基础镜像的别名发生冲突，请保留数据并检查 Docker 镜像。")
                        if not alias:
                            self.docker.run("tag", installed["work"], work_reference)
                self.docker.run("build", "--network", "default", "--label", RECIPE + "=" + self.recipes[role], "--build-arg", "WORK_IMAGE=" + work_reference, "-f", str(RESOURCES / ("Dockerfile." + role)), "-t", self.images[role], str(RESOURCES), timeout=2400, log=build_log, on_line=self.log, cancel=cancel)
                installed[role] = self.docker.inspect("image", self.images[role])["Id"]
            self.store.write("images.json", installed)
            self.log("环境安装完成。请导入节点，再检查和确认连接。")

    def install_prebuilt(self, progress=lambda data: None, cancel=None):
        from .downloads import manifest, download, RELEASE
        from .proxy import download_proxy
        with self.store.lock():
            info = self.doctor()
            available = {}
            for role, identifier in self.store.read("images.json", {}).items():
                obj = self.docker.inspect("image", identifier)
                if role in self.recipes and self.compatible_image(obj, role):
                    available[role] = obj["Id"]
            if len(available) == 3:
                progress({"stage": "done"})
                return
            if info["architecture"] not in ("x86_64", "amd64"):
                raise SPXError("预构建环境目前提供 x64 版本。ARM64 可选择从源码构建。")
            relay = self.store.settings()["relay"]
            via, route = download_proxy(relay)
            self.log("运行环境下载线路：" + route)
            progress({"stage": "manifest", "route": route})
            meta = manifest("linux/amd64", self.recipes, via)
            archive = download(RELEASE + meta["filename"], self.store.home / "cache" / meta["filename"], meta["sha256"], meta["bytes"], progress, cancel, via)
            if cancel and cancel.is_set():
                from .downloads import DownloadPaused
                raise DownloadPaused("安装已暂停，环境包已保留。")
            self._stop("运行环境正在更新，请在完成后重新核对连接。")
            progress({"stage": "import"})
            self.docker.run("load", "--input", str(archive), timeout=1200, log=self.store.home / "build.log", on_line=self.log, cancel=cancel)
            resolved = {}
            for role, identifier in meta["images"].items():
                obj = self.docker.inspect("image", identifier) or self.docker.inspect("image", meta["image_configs"][role])
                if not obj or obj.get("Architecture") != "amd64" or image_recipe(obj) != self.recipes[role]:
                    raise SPXError("导入的镜像与本版本不匹配，请重试。")
                resolved[role] = obj["Id"]
            self.store.write("images.json", {**resolved, **available})
            self.store.write("runtime-bundle.json", {"version": meta["version"], "sha256": meta["sha256"], "bytes": meta["bytes"]})
            progress({"stage": "done"})

    def image_ids(self):
        expected = self.store.read("images.json", {})
        if set(expected) != set(self.images):
            raise SPXError("请先安装运行环境。")
        for role, name in self.images.items():
            obj = self.docker.inspect("image", expected[role])
            if not self.compatible_image(obj, role):
                raise SPXError("运行镜像缺失或版本发生变化，请重新安装运行环境并检查连接。")
            self._image_abis[role] = "legacy" if image_recipe(obj) == LEGACY_RECIPES[role] else "spx"
        return expected

    def save_nodes(self, nodes: list[dict], append=False):
        if not nodes:
            raise SPXError("没有可导入的节点。")
        with self.store.lock():
            self._stop("已导入新节点，请重新检查和确认连接。")
            if append:
                nodes = [*nodes, *[node for node in self.store.read("nodes.json", []) if node["id"] not in {item["id"] for item in nodes}]]
            self.store.write("nodes.json", nodes)
            settings = self.store.settings()
            if not append or settings["selected"] not in {node["id"] for node in nodes}:
                settings["selected"] = nodes[0]["id"]
            self.store.write("settings.json", settings)

    def delete_node(self, identifier):
        with self.store.lock(timeout=30):
            self._stop("代理已删除，请重新配置并确认连接。")
            nodes = [node for node in self.store.read("nodes.json", []) if node["id"] != identifier]
            settings = self.store.settings()
            identifiers = {node["id"] for node in nodes}
            if settings["selected"] not in identifiers:
                settings["selected"] = nodes[0]["id"] if nodes else ""
            if settings["relay"].get("line_id") == identifier:
                settings["relay"] = {"enabled": False, "downloads": settings["relay"].get("downloads", True)}
            self.store.write("nodes.json", nodes)
            self.store.write("settings.json", settings)

    def clear_proxy_credentials(self):
        with self.store.lock(timeout=30):
            self._stop("代理凭据已清除，项目和工具账号卷已保留。")
            settings = self.store.settings()
            settings.update(selected="", relay={"enabled": False, "downloads": True})
            self.store.write("nodes.json", [])
            self.store.write("settings.json", settings)

    def save_settings(self, selected: str, timezone: str, context: str, relay=None):
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise SPXError("请填写有效的 IANA 时区，例如 America/Los_Angeles。") from error
        if not context.strip() or context.startswith("-"):
            raise SPXError("Docker 上下文名称无效。")
        with self.store.lock():
            old = self.store.settings()
            from .proxy import validate_relay, route_config
            relay = validate_relay(old["relay"] if relay is None else relay)
            if relay.get("mode") == "managed":
                from .line_security import managed_line, chain_outbounds
                line = self.node_by_id(relay["line_id"])
                managed_line(line, relay["server_ip"])
                if selected:
                    chain_outbounds(self.node_by_id(selected), relay, line)
            if selected:
                from .line_security import chain_outbounds
                outbounds, _ = chain_outbounds(self.node_by_id(selected), relay, line if relay.get("mode") == "managed" else None)
                self.backend.gateway_config(outbounds, "127.0.0.1", relay["enabled"])
            if old.get("context") != context and self.store.read("images.json"):
                raise SPXError("已安装的环境不能切换 Docker 上下文。请使用新的专用数据目录。")
            established = self.store.read("environment.json")
            if established and established["timezone"] != timezone:
                raise SPXError("已有持久化环境的时区固定。改变时区请使用新的专用数据目录。")
            old_route = route_config(old["relay"])
            new_route = route_config(relay)
            if (old["selected"], old["timezone"], old["context"], old_route) != (selected, timezone, context, new_route):
                self._stop("设置已更新，请重新检查连接。")
            self.store.write("settings.json", {**old, "selected": selected, "timezone": timezone, "context": context, "relay": relay})

    def node(self):
        return self.node_by_id(self.store.settings()["selected"])

    def node_by_id(self, selected):
        node = next((n for n in self.store.read("nodes.json", []) if n["id"] == selected), None)
        if not node:
            raise SPXError("请先导入并选择节点。")
        from .nodes import normalize
        try:
            validated = normalize(node["outbound"], node["label"])
            if validated["id"] != node["id"]:
                raise ValueError()
            return validated
        except (ValueError, KeyError, TypeError) as error:
            raise SPXError("保存的节点配置无效或发生变化，请重新导入节点。") from error

    def policy(self):
        settings = self.store.settings()
        from .proxy import route_config
        relay = route_config(settings["relay"])
        line = self.node_by_id(relay["line_id"]) if relay.get("mode") == "managed" else None
        result = {"node": self.node(), "line": line, "timezone": settings["timezone"], "context": settings["context"], "relay": relay, "recipe": self.recipe, "line_guard": 2, "network_policy": 1, "proxy_backend": self.backend.name}
        from .workspace_profiles import load, policy, SHARED
        workspace = load(self.store)
        if workspace["selected"] != SHARED or workspace["projects"]:
            result["workspace"] = policy(workspace)
        return fingerprint(result)

    def networks(self):
        from .network_policy import ensure
        return ensure(self)

    def ensure_container(self, role, image, arguments, command=(), name=None, resource_key=None, validate_existing=None):
        from .resource_limits import validate, budget, arguments as resource_arguments, apply_stopped, ROLES
        settings = self.store.settings()
        limits = budget(validate(settings.get("resources")), role, resource_key) if role in ROLES else None
        name = name or self.prefix + "-" + role
        storage = fingerprint(os.path.normcase(str(self.store.home)))[:24]
        obj = self.inspect(role, name)
        if obj:
            moved_gateway = role == "gateway" and (obj.get("Config", {}).get("Labels") or {}).get(STORAGE) != storage
            if obj["Image"] != image or moved_gateway:
                if role in ("gateway", "browser") and not obj["State"]["Running"]:
                    self.docker.run("rm", obj["Id"])
                    obj = None
                else:
                    raise SPXError("已有容器的镜像与本版本不同。请保留数据，使用新的专用数据目录。")
        if obj:
            if validate_existing is not None:
                validate_existing(obj)
            if limits is not None and settings.get("resources") is not None:
                # Docker update ignores memory=0. Only the data-free gateway
                # can be replaced to remove an existing hard memory limit;
                # project/session limits always stay finite and preserve IDs.
                reset_gateway = role == "gateway" and limits["memory_mb"] == 0 and obj.get("HostConfig", {}).get("Memory", 0) > 0
                if reset_gateway and not obj["State"]["Running"]:
                    self.docker.run("rm", obj["Id"])
                    obj = None
                else:
                    obj = apply_stopped(self, obj, limits)
        if obj:
            if not obj["State"]["Running"]:
                self.docker.run("start", name)
            return self.inspect(role, name)
        common = ["run", "-d", "--name", name, "--label", self.owner + "=" + self.store.instance, "--label", self.role + "=" + role, "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "512", "--env", "TZ=" + self.store.settings()["timezone"]]
        if role == "gateway":
            common += ["--label", STORAGE + "=" + storage]
        if limits is not None:
            common += resource_arguments(limits)
        self.docker.run(*common, *arguments, image, *command)
        return self.inspect(role, name)

    def setup(self):
        ids = self.image_ids()
        gateway_ip, session_ip = self.networks()
        from .proxy import loopback, validate_relay
        from .line_security import chain_outbounds, LINE_PROXY
        relay = validate_relay(self.store.settings()["relay"])
        line = self.node_by_id(relay["line_id"]) if relay.get("mode") == "managed" else None
        outbounds, forward_target = chain_outbounds(self.node(), relay, line)
        outbound = outbounds[0]
        if not relay["enabled"] and loopback(outbound["server"]) and outbound["type"] in ("socks", "http"):
            forward_target = {"host": outbound["server"], "port": outbound["server_port"]}
            outbound.update({"server": "127.0.0.1", "server_port": 2081})
        # Detoured destinations are resolved by the first hop. Host DNS would
        # disclose the landing name and defeat domain routing in v2ray.
        if not relay["enabled"]:
            try:
                answers = socket.getaddrinfo(outbound["server"], outbound["server_port"], socket.AF_INET, socket.SOCK_STREAM)
                outbound["server"] = answers[0][4][0]
            except OSError as error:
                raise SPXError("本机无法解析节点的 IPv4 地址。") from error
        directory = self.store.home / "gateway"
        directory.mkdir(exist_ok=True)
        config = self.backend.gateway_config(outbounds, gateway_ip, relay["enabled"])
        self.store.write("gateway/config.json", config)
        journal = self._image_abis.get("gateway") != "legacy"
        self.set_lease(time.time() + 300, {"lease_journal": journal}, reset=True)
        gateway = self.ensure_container("gateway", ids["gateway"], ["--user", str(getattr(os, "getuid", lambda: 0)()), "--network", self.internal, "--ip", gateway_ip, "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777", "--mount", f"type=bind,source={directory / 'lease.jsonl'},target=/config/lease.jsonl,readonly"])
        self.deliver_secret(gateway["Id"], "gateway", config)
        if self.external not in gateway["NetworkSettings"]["Networks"]:
            self.docker.run("network", "connect", "--gw-priority", "1", self.external, gateway["Id"])
        session = self.ensure_container("session", ids["work"], ["--network", self.internal, "--ip", session_ip, "--dns", "127.0.0.1", "--read-only", "--tmpfs", "/tmp"], ["sleep", "infinity"])
        self.store.write("environment.json", {"timezone": self.store.settings()["timezone"]})
        return {"gateway": gateway["Id"], "session": session["Id"], "proxy": f"http://{gateway_ip}:2080", "config_hash": fingerprint(config), "forward_target": forward_target, "line_proxy": LINE_PROXY if relay["enabled"] else None, "line_mode": relay.get("mode"), "lease_journal": journal}

    def ensure_forward(self, state):
        if not state.get("forward_target"):
            return
        for attempt in range(40):
            current = self.store.read("forward.json", {})
            if current.get("gateway") == state["gateway"] and current.get("policy") == state["policy"] and time.time() - current.get("heartbeat", 0) < 5:
                try:
                    # The host heartbeat can precede Docker exec and the guest
                    # listener. Check the actual endpoint instead of sleeping.
                    self.docker.run("exec", state["gateway"], "python3", "-c", "import socket; socket.create_connection(('127.0.0.1',2081),.5).close()", timeout=3)
                    return
                except SPXError:
                    pass
            if attempt % 4 == 0:
                self.background("forward")
            time.sleep(.25)
        raise SPXError("无法连接本机线路代理。请先启动线路客户端并核对监听地址、端口和认证信息。")

    def probe(self, state, detailed=True):
        code = (PACKAGE_RESOURCES / "checks/exit_probe.py").read_text(encoding="utf-8")
        # Reuse the read-only session and its isolated network. Avoid creating a
        # disposable container and querying geography for every monitor tick.
        output = self.docker.run("exec", "--env", "NO_PROXY=", "--env", "no_proxy=", state["session"], "python3", "-c", code, state["proxy"], *(["--details"] if detailed else []), timeout=45)
        try:
            result = json.loads(output)
            ipaddress.IPv4Address(result["ip"])
            if result.get("direct_blocked") is not True:
                raise ValueError("direct connection allowed")
            return result
        except (ValueError, KeyError) as error:
            raise SPXError("出口核对或直连阻断检查未通过。") from error

    def probe_line(self, state):
        from .line_security import LINE_CHECK_CODE
        try:
            output = self.docker.run("exec", state["gateway"], "python3", "-c", LINE_CHECK_CODE, timeout=30)
            value = json.loads(output)
            if not ipaddress.IPv4Address(value["ip"]).is_global:
                raise ValueError()
            return value
        except (SPXError, ValueError, KeyError, TypeError) as error:
            raise LineSecurityError("前置线路出口检查失败，已拒绝继续连接落地。请检查线路，不会改走直连。") from error

    def wait_line_listener(self, state):
        if not state.get("line_proxy"):
            return
        for _ in range(40):
            try:
                self.docker.run("exec", state["gateway"], "python3", "-c", "import socket; socket.create_connection(('127.0.0.1',2082),.3).close()", timeout=3)
                return
            except SPXError:
                time.sleep(.1)
        raise LineSecurityError("前置线路检查入口未能启动，请检查网关日志和节点配置。")

    def probe_chain(self, state, detailed=True, timings=None):
        def measured(scope, action):
            if timings is None:
                return action()
            from .network_diagnostics import measured_probe
            return measured_probe(scope, action, timings)
        line = None
        if state.get("line_proxy"):
            line = measured("first_hop", lambda: self.probe_line(state))
            expected = self.store.settings()["relay"].get("expected_ip") or (state.get("evidence") or {}).get("line_ip")
            if expected and line["ip"] != expected:
                if timings:
                    timings[-1].update(result="unexpected_exit", error_code="unexpected_exit")
                raise LineSecurityError("前置线路出口 IP 已改变，已停止环境。请检查 v2ray 分流、线路选择或直连回退，再重新核对。")
        evidence = dict(measured("final_exit", lambda: self.probe(state, detailed=detailed)))
        if line:
            evidence.update(line_ip=line["ip"], line_mode=state["line_mode"])
        return evidence

    def check(self):
        with self.store.lock(timeout=45, on_wait=lambda: self.log("正在等待当前安全检查完成，随后重新检查连接…")):
            self.doctor()
            self._stop("正在检查连接。")
            try:
                # A pre-sandbox browser remains stopped after an upgrade. It
                # must be retired before confirm/guard audits every owned
                # container. Keep the named Profile/download volumes; the next
                # browser launch still validates the replacement and renderer.
                self._retire_stopped_browser()
                state = self.setup()
                # Network migration inside setup can stop again. Clear its
                # signal only after setup, while runtime is still stopped, and
                # before either an old or a new guard can observe a new policy.
                self.take_over_legacy_guard()
                state.update({"phase": "checking", "policy": self.policy()})
                self.store.write("runtime.json", state)
                self.ensure_forward(state)
                self.wait_line_listener(state)
                self.log("通过所选节点核对两个出口来源，并检查容器直连是否被阻断…")
                evidence = self.probe_chain(state)
                state.update({"phase": "review", "policy": self.policy(), "checked": time.time(), "evidence": evidence})
                self.store.write("runtime.json", state)
                return evidence
            except Exception as error:
                self._stop(str(error) if isinstance(error, LineSecurityError) else "连接检查失败，环境已停止。")
                raise

    def take_over_legacy_guard(self):
        # This applies to every upgrade, not just the original product rename:
        # a 0.8.x guard uses an older policy algorithm and must not see a new
        # ready session before it exits. Keep stopped until its lock is released.
        notified = False
        deadline = time.monotonic() + 40
        while True:
            try:
                with self.store.lock("guard"):
                    (self.store.home / "guard-stop.json").unlink(missing_ok=True)
                    if self.store.read("controller.json", {}) != {"app": "enge-spx"}:
                        self.store.write("controller.json", {"app": "enge-spx"})
                return
            except SPXError:
                if not notified:
                    self.log("正在等待上一个后台监测退出，升级旧版时最长约 40 秒；数据保留。")
                    notified = True
                if time.monotonic() >= deadline:
                    raise SPXError("旧版后台监测尚未退出，请先退出旧版程序，再重新检查连接。")
                time.sleep(.2)

    def audit_topology(self, state):
        session, gateway = self.inspect("session"), self.inspect("gateway")
        if not session or not gateway or session["Id"] != state["session"] or gateway["Id"] != state["gateway"] or not session["State"]["Running"] or not gateway["State"]["Running"]:
            raise SPXError("容器已停止或重新创建，请重新检查和确认连接。")
        if set(session["NetworkSettings"]["Networks"]) != {self.internal} or set(gateway["NetworkSettings"]["Networks"]) != {self.internal, self.external}:
            raise SPXError("检测到容器网络发生变化。")
        if session.get("HostConfig", {}).get("Dns") != ["127.0.0.1"]:
            raise SPXError("工作区 DNS 配置已改变，环境已拒绝继续连接。")
        from .network_policy import validate as validate_network
        validate_network(self, self.docker.inspect("network", self.internal), True)
        validate_network(self, self.docker.inspect("network", self.external), False)
        config = self.store.read("gateway/config.json")
        if fingerprint(config) != state["config_hash"] or self.policy() != state["policy"]:
            raise SPXError("节点或运行配置已改变，请重新检查。")
        if state.get("forward_target"):
            forward = self.store.read("forward.json", {})
            if forward.get("gateway") != state["gateway"] or forward.get("policy") != state["policy"] or time.time() - forward.get("heartbeat", 0) > 12:
                raise SPXError("本机线路中转已断开，请重新检查连接。")
        from .workspace_profiles import FILE, MARKER, load, validate_mounts
        workspace = load(self.store)
        audit_mounts = (self.store.home / FILE).exists() or (self.store.home / MARKER).exists()
        for name in self.managed():
            obj = self.docker.inspect("container", name)
            self.owned(obj)
            role = obj["Config"]["Labels"][self.role]
            if role == "browser":
                from .browser_security import validate_container
                validate_container(obj)
            if audit_mounts and role in ("project", "browser"):
                validate_mounts(self, obj, workspace)
            if role in ("project", "browser") and obj["HostConfig"]["NetworkMode"] != "container:" + state["session"]:
                raise SPXError("工作容器的网络空间已改变。")

    def confirm(self):
        with self.store.lock():
            state = self.store.read("runtime.json", {})
            try:
                if state.get("phase") != "review" or time.time() - state["checked"] > 300:
                    raise SPXError("检查结果已过期，请重新检查节点。")
                self.audit_topology(state)
                evidence = self.probe_chain(state)
                if evidence["ip"] != state["evidence"]["ip"]:
                    raise SPXError("复核时出口 IP 已改变，请重新检查和核对。")
                state.update({"phase": "ready", "evidence": evidence, "heartbeat": time.time(), "confirmed": time.time(), "browser_token": secrets.token_hex(32)})
                self.set_lease(time.time() + 180, state)
                self.store.write("runtime.json", state)
                self.start_guard()
                return evidence
            except Exception as error:
                self._stop(str(error) if isinstance(error, LineSecurityError) else "连接尚未确认，环境已停止。")
                raise

    def background(self, action):
        args = ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "enge_spx"])
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
        with (self.store.home / (action + ".log")).open("a", encoding="utf-8") as log:
            subprocess.Popen([*args, "--data", str(self.store.home), action], stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=os.environ.copy(), cwd=str(Path(__file__).resolve().parent.parent), creationflags=flags, start_new_session=os.name != "nt")

    def start_guard(self):
        self.background("guard")

    def ready(self, timings=None):
        state = self.store.read("runtime.json", {})
        if state.get("phase") != "ready":
            raise SPXError("请先检查节点、核对出口 IP 并确认连接。")
        try:
            self.audit_topology(state)
            if time.time() - state.get("heartbeat", 0) > 100:
                raise SPXError("连接监测进程已失联，请重新检查连接。")
            result = self.probe_chain(state, detailed=False) if timings is None else self.probe_chain(state, detailed=False, timings=timings)
            if result["ip"] != state["evidence"]["ip"]:
                if timings:
                    timings[-1].update(result="unexpected_exit", error_code="unexpected_exit")
                raise SPXError("检测到出口 IP 改变，环境已停止。")
            state["heartbeat"] = time.time()
            self.set_lease(time.time() + 180, state)
            self.store.write("runtime.json", state)
            return state
        except OSError:
            # Preserve the last successful lease on an I/O failure. The guard
            # retries without extending it; a persistent failure still expires.
            raise
        except Exception as error:
            self._stop(str(error) if isinstance(error, LineSecurityError) else "连接监测未通过，请重新检查节点。")
            raise

    def guard(self):
        from .process_metrics import tracked
        try:
            with self.store.lock("guard"), tracked(self.store, "guard"):
                stop_signal = self.store.home / "guard-stop.json"
                while not stop_signal.is_file() and self.store.read("runtime.json", {}).get("phase") == "ready":
                    try:
                        with self.store.lock():
                            self.ready()
                    except OSError as error:
                        # A transient Windows sharing conflict must not kill the
                        # only lease-renewal process. No successful write means
                        # no renewal: the gateway still expires if it persists.
                        self.log(f"监测状态写入暂时失败，将自动重试（{type(error).__name__}，系统代码 {getattr(error, 'winerror', None) or error.errno}）。")
                        time.sleep(3)
                        continue
                    except SPXError:
                        if self.store.read("runtime.json", {}).get("phase") != "ready":
                            break
                    # Keep the same network-check cadence. Only poll a cheap,
                    # non-secret stop signal during sleep, so stop/recheck does
                    # not wait a whole monitor interval or reuse older code.
                    for _ in range(30):
                        if stop_signal.is_file():
                            return
                        time.sleep(1)
        except SPXError:
            pass

    def managed(self):
        return self.docker.run("ps", "-aq", "--filter", "label=" + self.owner + "=" + self.store.instance).splitlines()

    def set_lease(self, expires, state, reset=False):
        if state.get("lease_journal"):
            from .lease import write_lease
            write_lease(self.store, expires, reset)
        else:
            self.store.write("gateway/lease.json", {"expires": expires})

    def _stop(self, reason="环境已停止，账号和项目数据已保留。"):
        try:
            state = self.store.read("runtime.json", {})
        except SPXError:
            state = {"lease_journal": (self.store.home / "gateway/lease.jsonl").is_file()}
        write_error = None
        try:
            self.store.write("guard-stop.json", {"schema": 1, "requested": True})
        except (OSError, SPXError) as error:
            write_error = error
        try:
            self.store.write("runtime.json", {"phase": "stopped", "reason": reason})
        except (OSError, SPXError) as error:
            write_error = error
        try:
            self.set_lease(0, state)
        except (OSError, SPXError) as error:
            write_error = error
        if not self.docker.executable or not self.store.read("images.json"):
            self.clear_runtime_references()
            if write_error:
                raise write_error
            return
        # Stop the gateway first: an unconfirmed state must not leave an outbound route.
        objects = [self.owned(self.docker.inspect("container", name)) for name in self.managed()]
        objects.sort(key=lambda o: o["Config"]["Labels"][self.role] != "gateway")
        failures = []
        for obj in objects:
            if obj["State"]["Running"]:
                try:
                    self.docker.run("stop", "--time", "8", obj["Id"], timeout=25)
                except SPXError:
                    failures.append(obj["Id"])
        if failures:
            # A failed graceful stop still has to close this installation's network.
            for identifier in failures:
                self.docker.run("kill", identifier, timeout=15)
        self.clear_runtime_references()
        if write_error:
            raise write_error

    def clear_runtime_references(self):
        for name in ("gateway/config.json", "relay.json", "browser-token.json"):
            (self.store.home / name).unlink(missing_ok=True)
        self.docker.secret_env.clear()

    def stop(self):
        with self.store.lock(timeout=45, on_wait=lambda: self.log("正在等待当前安全检查完成后停止工作区…")):
            self._stop()

    def shutdown(self):
        """Verified user exit: own workspace/services only; never quits Desktop."""
        with self.store.lock(timeout=45, on_wait=lambda: self.log("等待当前安全检查完成，随后停止工作区并退出…")):
            return self._shutdown_locked()

    def _shutdown_locked(self):
        """Caller holds the operation lock through stop, services and verification."""
        installed = bool(self.store.read("images.json", {}))
        self.log("正在撤销连接授权并停止本实例工作区…")
        self._stop()
        if installed and not self.docker.executable:
            raise SPXError("未找到 Docker 命令行工具，已撤销本实例连接授权，但无法核验容器是否停止。界面会保留。")
        deadline = time.monotonic() + 45
        self.log("正在等待安全监测、中转和浏览器显示服务安全退出…")
        for name in ("guard", "forward", "relay"):
            with self.store.lock(name, timeout=max(0, deadline - time.monotonic())):
                pass
        if self.docker.executable and self.store.read("images.json", {}):
            for identifier in self.managed():
                obj = self.owned(self.docker.inspect("container", identifier))
                if obj["State"]["Running"]:
                    raise SPXError("仍检测到本实例的运行容器，界面会保留，请重试退出。")
        self.log("工作区与后台服务已停止，项目和账号数据保留。")
        return {"workspace_stopped": True, "background_stopped": True, "docker_desktop_kept": True}

    def workspace_profiles(self):
        from .workspace_profiles import load
        return load(self.store)

    def network_diagnostics(self, browser=True):
        from .network_diagnostics import collect
        return collect(self, browser=browser)

    def _save_workspace_locked(self, config, previous):
        from .workspace_profiles import FILE, MARKER, PREVIOUS, policy
        if config == previous:
            return config
        if policy(config) != policy(previous):
            self.log("正在停止当前工作区，切换身份或项目目录权限…")
            self._shutdown_locked()
        self.store.write(PREVIOUS, {"schema": 1, "config": previous})
        # Fence first initialization before writing the selection. An interrupted
        # first write must require explicit restore, not look like legacy shared.
        if self.store.read(MARKER) != {"schema": 1, "enabled": True}:
            self.store.write(MARKER, {"schema": 1, "enabled": True})
        self.store.write(FILE, config)
        return config

    def create_workspace_profile(self, name):
        from .workspace_profiles import display_name, validate
        name = display_name(name)
        with self.store.lock(timeout=45):
            previous = self.workspace_profiles()
            config = validate(previous)
            if name.casefold() in {value.casefold() for value in config["profiles"].values()}:
                raise SPXError("已有同名身份，请使用不同名称。")
            identity = secrets.token_hex(6)
            while identity in config["profiles"]:
                identity = secrets.token_hex(6)
            config["profiles"][identity] = name
            config = validate(config)
            self._save_workspace_locked(config, previous)
            return {"profile": identity, "config": config}

    def configure_workspace(self, identity, path=None, access="ro"):
        from .workspace_profiles import validate, profile_id
        if not profile_id(identity) or access not in ("ro", "rw"):
            raise SPXError("工作区身份或只读/读写选项无效。")
        directory, key = self.store.project(path) if path else (None, None)
        with self.store.lock(timeout=45, on_wait=lambda: self.log("等待当前操作完成后应用工作区身份…")):
            previous = self.workspace_profiles()
            config = validate(previous)
            if identity not in config["profiles"]:
                raise SPXError("所选工作区身份不存在；不会使用默认账号替代。")
            config["selected"] = identity
            if key:
                config["projects"][key] = {"profile": identity, "access": access}
            return self._save_workspace_locked(validate(config), previous)

    def restore_workspace_profiles(self):
        from .workspace_profiles import FILE, MARKER, PREVIOUS, validate, check_files
        with self.store.lock(timeout=45):
            check_files(self.store, PREVIOUS)
            backup = self.store.read(PREVIOUS, {})
            if not isinstance(backup, dict) or set(backup) != {"schema", "config"} or type(backup["schema"]) is not int or backup["schema"] != 1 or backup["config"] is None:
                raise SPXError("没有可恢复的上次工作区身份配置。")
            config = validate(backup["config"])
            try:
                current = self.workspace_profiles()
            except SPXError:
                # Explicit recovery only, never an implicit shared-account fallback.
                self._shutdown_locked()
                self.store.write(FILE, config)
                self.store.write(MARKER, {"schema": 1, "enabled": True})
                return config
            # Restoring selection/authorization never forgets newly created data.
            config["profiles"].update(current["profiles"])
            return self._save_workspace_locked(validate(config), current)

    def save_resources(self, config):
        from .resource_limits import validate
        if not isinstance(config, dict):
            raise SPXError("请提供完整的 schema=1 资源设置对象。")
        config = validate(config)
        with self.store.lock(timeout=45, on_wait=lambda: self.log("等待当前操作完成后保存资源预算…")):
            settings = self.store.settings()
            try:
                previous = validate(settings.get("resources"))
            except SPXError:
                previous = None  # Never copy unknown/unvalidated data to a public backup.
            if previous != config:
                self._stop("资源预算已保存，工作区保持停止。重新检查连接后应用，账号和项目数据保留。")
                if previous is not None:
                    self.store.write("resources-previous.json", {"schema": 1, "resources": previous})
            if settings.get("resources") != config:
                settings["resources"] = config
                self.store.write("settings.json", settings)
            return config

    def restore_resources(self):
        previous = self.store.read("resources-previous.json", {})
        if not isinstance(previous, dict) or set(previous) != {"schema", "resources"} or type(previous.get("schema")) is not int or previous["schema"] != 1 or not isinstance(previous["resources"], dict):
            raise SPXError("没有可恢复的上次资源设置。")
        return self.save_resources(previous["resources"])

    def stop_browser(self):
        with self.store.lock(timeout=45, on_wait=lambda: self.log("等待当前操作完成后停止浏览器…")):
            obj = self.inspect("browser")
            write_error = None
            try:
                self.store.write("browser-state.json", {"schema": 1, "id": obj["Id"] if obj else "", "phase": "stopped"})
            except (SPXError, OSError) as error:
                write_error = error
            if obj and obj["State"]["Running"]:
                try:
                    self.docker.run("stop", "--time", "8", obj["Id"], timeout=25)
                except SPXError:
                    self.docker.run("kill", obj["Id"], timeout=15)
            if write_error:
                raise write_error
            return {"browser": "stopped", "workspace_kept": True, "profile_kept": True}

    def save_terminal(self, config):
        from .terminal import validate, resolve
        config = validate(config)
        resolve(config)
        with self.store.lock():
            settings = self.store.settings()
            settings["terminal"] = config
            self.store.write("settings.json", settings)
        return config

    def migrate_storage(self, target, progress=lambda value: None):
        from .storage import migrate_home
        return migrate_home(self.store, target, self._stop, progress)

    def proxy_env(self, state):
        result = []
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            result += ["--env", key + "=" + state["proxy"]]
        return [*result, "--env", "NO_PROXY=localhost,127.0.0.1,::1", "--env", "no_proxy=localhost,127.0.0.1,::1", "--env", "BROWSER=/usr/local/bin/xdg-open", "--env", "TZ=" + self.store.settings()["timezone"]]

    def control_env(self, state):
        self.secret_values.add(state["browser_token"])
        self.docker.secret_env["SPX_BROWSER_TOKEN"] = state["browser_token"]
        result = ["--env", "SPX_BROWSER_TOKEN"]
        if self.store.legacy:
            self.docker.secret_env[LEGACY_BROWSER_TOKEN] = state["browser_token"]
            result += ["--env", LEGACY_BROWSER_TOKEN]
        return result

    def deliver_secret(self, container, role, value):
        from .redaction import values
        self.secret_values.update(values(value))
        code = (RESOURCES / "runtime_secret.py").read_text(encoding="utf-8")
        self.docker.run("exec", "-i", container, "python3", "-c", code, role, input_data=json.dumps(value, separators=(",", ":")))

    def _retire_stopped_browser(self):
        old = self.inspect("browser")
        if old and not old["State"]["Running"]:
            self.docker.run("rm", old["Id"])
        return old

    def _browser(self, state):
        from .browser_security import arguments, validate_container, validate_status
        from .workspace_profiles import PROFILE, volumes, validate_mounts
        workspace = self.workspace_profiles()
        identity = workspace["selected"]
        data = volumes(self, identity)
        def verify(obj):
            validate_container(obj)
            validate_mounts(self, obj, workspace)
        ids = self.image_ids()
        # A stopped browser may contain an old one-time display token. Replace its
        # container, keeping its profile and downloads in dedicated persistent volumes.
        old = self._retire_stopped_browser()
        try:
            obj = self.ensure_container("browser", ids["browser"], ["--label", PROFILE + "=" + identity, "--network", "container:" + state["session"], "--shm-size", "512m", *arguments(), "--volume", data["browser-home"] + ":/home/workspace", "--volume", data["downloads"] + ":/home/workspace/Downloads", *self.proxy_env(state)], validate_existing=verify)
            verify(obj)
        except SPXError:
            self._stop("浏览器身份、挂载或沙箱核验失败，工作区已停止。")
            raise
        if not old or not old["State"]["Running"]:
            self.store.write("browser-state.json", {"schema": 1, "id": obj["Id"], "phase": "running"})
            self.deliver_secret(obj["Id"], "browser", {"token": state["browser_token"], "proxy": state["proxy"], "legacy": self.store.legacy})
        for _ in range(40):
            try:
                report = self.docker.run("exec", obj["Id"], "python3", "-c", "import json,socket; socket.create_connection(('127.0.0.1',6081),.3).close(); print(open('/tmp/spx-sandbox-status.json').read())", timeout=3)
                validate_status(json.loads(report))
                break
            except SPXError:
                if not self.inspect("browser")["State"]["Running"]:
                    try:
                        self.log("浏览器启动诊断：" + self.docker.run("logs", "--tail", "15", obj["Id"])[-4000:])
                    except SPXError:
                        pass
                    raise SPXError("浏览器沙箱初始化或启动失败，请检查内核 user namespaces、seccomp 与 Docker Desktop 中此浏览器容器的日志；不会回退到无沙箱模式。")
                time.sleep(.5)
        else:
            raise SPXError("共享浏览器启动超时，请重试。")
        self.viewer_assets(obj)
        descriptor = self.display_relay(obj, state)
        token = urllib.parse.quote("websockify?token=" + state["browser_token"], safe="")
        return descriptor["origin"] + f"/vnc.html?autoconnect=true&reconnect=true&reconnect_delay=2000&resize=scale&path={token}"

    def viewer_assets(self, browser):
        if self.store.read("viewer-assets.json", {}).get("image") == browser["Image"] and (self.store.home / "viewer-assets/vnc.html").is_file():
            return
        self.log("准备本机浏览器显示组件…")
        archive = self.store.home / "viewer-assets.zip"
        script = "import os,sys,zipfile; from pathlib import Path; root=Path('/usr/share/novnc'); z=zipfile.ZipFile(sys.stdout.buffer,'w',zipfile.ZIP_DEFLATED); n=0\nfor directory,dirs,files in os.walk(root,followlinks=True):\n for name in files:\n  p=Path(directory)/name; n+=1\n  if n>2000: raise ValueError('Too many files')\n  z.writestr(p.relative_to(root).as_posix(),p.read_bytes())\nz.close()"
        with archive.open("wb") as stream:
            result = subprocess.run(self.docker.command("exec", browser["Id"], "python3", "-c", script), stdout=stream, stderr=subprocess.PIPE, env=self.docker.environment(), timeout=60, creationflags=HIDDEN)
        if result.returncode or archive.stat().st_size > 20 * 1024 * 1024:
            raise SPXError("无法提取浏览器显示组件。")
        root = (self.store.home / "viewer-assets").resolve()
        root.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            if sum(i.file_size for i in bundle.infolist()) > 40 * 1024 * 1024:
                raise SPXError("浏览器显示组件大小异常。")
            for item in bundle.infolist():
                target = (root / item.filename).resolve()
                if root not in target.parents or "\\" in item.filename or ":" in item.filename:
                    raise SPXError("浏览器显示组件路径异常。")
                if not item.is_dir():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(item))
        archive.unlink(missing_ok=True)
        self.store.write("viewer-assets.json", {"image": browser["Image"]})

    def display_relay(self, browser, state):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(40):
            descriptor = self.store.read("relay.json", {})
            origin = descriptor.get("origin", "")
            parsed = urllib.parse.urlsplit(origin)
            if parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and descriptor.get("browser") == browser["Id"] and descriptor.get("token") == state["browser_token"]:
                try:
                    request = urllib.request.Request(origin + "/control/status", headers={"X-SPX-Control": descriptor["control"]})
                    with opener.open(request, timeout=1) as response:
                        if json.load(response).get("browser") == browser["Id"]:
                            return descriptor
                except (OSError, ValueError, KeyError):
                    pass
            if attempt % 4 == 0:
                self.background("relay")
            time.sleep(.5)
        raise SPXError("本机显示服务未能启动，请查看数据目录中的 relay.log。")

    def browser(self, expected_profile=None):
        with self.store.lock(timeout=30, on_wait=lambda: self.log("等待后台连接检查完成，随后自动打开浏览器…")):
            if expected_profile is not None and self.workspace_profiles()["selected"] != expected_profile:
                raise SPXError("当前身份已改变，请先应用所选身份并重新确认连接。")
            state = self.ready()
            url = self._browser(state)
        webbrowser.open(url)
        return url

    def _project(self, path, state):
        from .workspace_profiles import project_plan, project_arguments, volumes, validate_mounts
        workspace = self.workspace_profiles()
        plan = project_plan(self, path, workspace)
        directory, key = plan["directory"], plan["key"]
        data = volumes(self, plan["profile"])
        def verify(obj):
            validate_mounts(self, obj, workspace, plan)
        ids = self.image_ids()
        try:
            obj = self.ensure_container("project", ids["work"], ["--network", "container:" + state["session"], *project_arguments(plan), "--volume", data["tools-home"] + ":/home/workspace", "--workdir", "/workspace/" + key, *self.proxy_env(state)], name=plan["name"], resource_key=key, validate_existing=verify)
            verify(obj)
        except SPXError:
            self._stop("项目身份、目录或权限核验失败，工作区已停止。")
            raise
        settings = self.store.settings()
        projects = list(dict.fromkeys([*settings["projects"], str(directory)]))
        if projects != settings["projects"]:
            settings["projects"] = projects
            self.store.write("settings.json", settings)
        return obj, key

    def tool_command(self, path, command, interactive=True, browser=None):
        argv, _ = self._tool_session(path, command, interactive, browser)
        return argv

    def _tool_session(self, path, command, interactive=True, browser=None, expected_workspace=None):
        # The guard checks immediately after confirmation and every 30 seconds.
        # Wait for its lock before executing anything; never retry the launch.
        with self.store.lock(timeout=30, on_wait=lambda: self.log("等待后台连接检查完成，随后自动启动工作区…")):
            from .workspace_profiles import project_plan
            plan = project_plan(self, path)
            if expected_workspace is not None and (plan["profile"], plan["access"]) != expected_workspace:
                raise SPXError("项目身份或目录权限已改变，请先应用设置并重新确认连接。")
            state = self.ready()
            if browser is None:
                from .resource_limits import validate
                browser = validate(self.store.settings().get("resources"))["auto_browser"]
            url = self._browser(state) if browser else None
            obj, key = self._project(path, state)
            self.prepared_session, self.prepared_container = state["session"], obj["Id"]
            flags = ["-it"] if interactive else ["-i"]
            return self.docker.command("exec", *flags, "--workdir", "/workspace/" + key, *self.proxy_env(state), *self.control_env(state), obj["Id"], *command), url

    def terminal(self, path, tool, expected_workspace=None):
        from .terminal import launch, resolve
        from .invocation import console_entry
        if tool not in TOOLS:
            raise SPXError("未知工具。")
        if os.name != "nt":
            raise SPXError("此按钮在 Windows 中打开终端；其他系统请使用命令行入口。")
        config = self.store.settings()["terminal"]
        resolve(config)
        _, url = self._tool_session(path, TOOLS[tool], browser=True if tool.startswith("login-") else None, expected_workspace=expected_workspace)
        directory, _ = self.store.project(path)
        command = [*console_entry(), "--data", str(self.store.home), "--project", str(directory), "attach", tool, "--session", self.prepared_session, "--container", self.prepared_container]
        # The terminal gets a public CLI invocation, never the token environment.
        launch(config, command, str(directory), "ENGE SPX · " + tool, docker_environment(self.docker.executable))
        # Open the viewer so any account authorization URL stays in Chromium.
        if url:
            webbrowser.open(url)

    def attach_command(self, path, tool, session, container, interactive=True):
        if tool not in TOOLS:
            raise SPXError("未知工作区工具。")
        with self.store.lock(timeout=30):
            state = self.store.read("runtime.json", {})
            if state.get("phase") != "ready" or state.get("session") != session or time.time() - state.get("heartbeat", 0) > 100:
                raise SPXError("工作区连接已改变，请返回 ENGE SPX 重新打开工具。")
            self.audit_topology(state)
            from .workspace_profiles import project_plan, validate_mounts
            plan = project_plan(self, path)
            key = plan["key"]
            obj = self.inspect("project", plan["name"])
            if not obj or obj["Id"] != container or not obj["State"]["Running"] or obj["HostConfig"]["NetworkMode"] != "container:" + session:
                raise SPXError("项目容器已改变，请返回 ENGE SPX 重新打开工具。")
            validate_mounts(self, obj, plan=plan)
            return self.docker.command("exec", *( ["-it"] if interactive else ["-i"]), "--workdir", "/workspace/" + key, *self.proxy_env(state), *self.control_env(state), container, *TOOLS[tool])

    def status(self):
        return status_snapshot(self.store)
