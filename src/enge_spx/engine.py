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
from .brand import CONTAINERS, LEGACY_LABEL_ROOT
from .compat import LEGACY_RECIPES, LEGACY_RUNTIME_DIRECTORY, LEGACY_BROWSER_TOKEN
from .docker_env import environment as docker_environment

OWNER = "io.enge.spx.instance"
ROLE = "io.enge.spx.role"
STORAGE = "io.enge.spx.storage"
RECIPE = "io.enge.spx.recipe"
GATEWAY_IMAGE = "ghcr.io/sagernet/sing-box:v1.14.3"
RESOURCES = CONTAINERS
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def image_recipe(image):
    labels = image.get("Config", {}).get("Labels") or {}
    return labels.get(RECIPE, labels.get(LEGACY_LABEL_ROOT + ".recipe"))


class Docker:
    @staticmethod
    def desktop_app():
        if os.name != "nt":
            return None
        roots = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop"]
        return next((root / "Docker Desktop.exe" for root in roots if (root / "Docker Desktop.exe").is_file()), None)

    def __init__(self, context: str):
        candidates = [shutil.which("docker")]
        if os.name == "nt":
            candidates += [str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe")]
            candidates += [str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe")]
        self.executable = next((x for x in candidates if x and Path(x).is_file()), None)
        self.context = context

    def command(self, *args) -> list[str]:
        if not self.executable:
            raise SPXError("未找到 Docker Desktop，请安装并启动 Docker Desktop，切换到 Linux containers。")
        return [self.executable, "--context", self.context, *map(str, args)]

    def environment(self):
        # A desktop shortcut can inherit PATH from before Docker was installed.
        # The absolute CLI path alone does not make its credential helpers visible.
        return docker_environment(self.executable)

    def run(self, *args, timeout=60, log: Path | None = None, on_line=None, cancel=None) -> str:
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
                result = subprocess.run(self.command(*args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=self.environment(), creationflags=HIDDEN)
                output, error = result.stdout, result.stderr.strip()[-1500:]
        except subprocess.TimeoutExpired as error:
            raise SPXError("Docker 操作超时，请检查 Docker Desktop 状态及运行日志。") from error
        except OSError as error:
            raise SPXError("Docker 无法启动，请检查 Docker Desktop 安装。") from error
        if result.returncode:
            raise SPXError("Docker 操作失败：" + error)
        return output.strip()

    def inspect(self, kind: str, name: str):
        try:
            return json.loads(self.run(kind, "inspect", name))[0]
        except SPXError as error:
            if any(x in str(error).lower() for x in ("no such", "not found")):
                return None
            raise


class Engine:
    def __init__(self, store: Store, log=lambda message: None):
        self.store, self.log = store, log
        self.settings = store.settings()
        self.docker = Docker(self.settings["context"])
        self.owner = LEGACY_LABEL_ROOT + ".instance" if store.legacy else OWNER
        self.role = LEGACY_LABEL_ROOT + ".role" if store.legacy else ROLE
        self.prefix = ("ewbw-" if store.legacy else "spx-") + store.instance
        self.internal, self.external = self.prefix + "-internal", self.prefix + "-external"
        files = {p.relative_to(RESOURCES).as_posix(): p.read_text(encoding="utf-8") for p in sorted(RESOURCES.rglob("*")) if p.is_file() and "__pycache__" not in str(p)}
        self.recipe = fingerprint(files)[:12]
        self.recipes = {role: fingerprint({name: files[name] for name in names})[:12] for role, names in {"gateway": ["Dockerfile.gateway", "gateway.py", "tunnel.py"], "work": ["Dockerfile.work", "probe.py", "open_browser.py"]}.items()}
        self.recipes["browser"] = fingerprint({"work": self.recipes["work"], **{name: files[name] for name in ("Dockerfile.browser", "browser.py", "vnc_stdio.py", "chromium-policy.json")}})[:12]
        self.images = {role: "enge-spx/" + role + ":" + self.recipes[role] for role in ("gateway", "work", "browser")}
        self._image_abis = {}

    def compatible_image(self, image, role):
        if not image or role not in self.recipes:
            return False
        recipe = image_recipe(image)
        return recipe == self.recipes[role] or self.store.legacy and recipe == LEGACY_RECIPES[role]

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

    def doctor(self) -> dict:
        context = json.loads(self.docker.run("context", "inspect", self.docker.context))[0]
        endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not endpoint.startswith(("npipe://", "unix://")):
            raise SPXError("请选择本机 Docker Desktop 上下文；此版本不支持远程 Docker。")
        info = json.loads(self.docker.run("info", "--format", "{{json .}}"))
        if info.get("OSType") != "linux":
            raise SPXError("Docker 当前未使用 Linux containers，请在 Docker Desktop 中切换。")
        if int(info.get("ServerVersion", "0").split(".")[0]) < 28:
            raise SPXError("需要 Docker Engine 28 或更新版本，请更新 Docker Desktop。")
        arch = info.get("Architecture", "")
        if arch not in ("x86_64", "amd64", "aarch64", "arm64"):
            raise SPXError("仅支持 x64 或 ARM64 的 Linux 容器引擎。")
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

    def save_nodes(self, nodes: list[dict]):
        with self.store.lock():
            self._stop("已导入新节点，请重新检查和确认连接。")
            self.store.write("nodes.json", nodes)
            settings = self.store.settings()
            settings["selected"] = nodes[0]["id"]
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
            from .proxy import validate_relay
            relay = validate_relay(old["relay"] if relay is None else relay)
            if old.get("context") != context and self.store.read("images.json"):
                raise SPXError("已安装的环境不能切换 Docker 上下文。请使用新的专用数据目录。")
            established = self.store.read("environment.json")
            if established and established["timezone"] != timezone:
                raise SPXError("已有持久化环境的时区固定。改变时区请使用新的专用数据目录。")
            old_route = {k: v for k, v in old["relay"].items() if k != "downloads"}
            new_route = {k: v for k, v in relay.items() if k != "downloads"}
            if (old["selected"], old["timezone"], old["context"], old_route) != (selected, timezone, context, new_route):
                self._stop("设置已更新，请重新检查连接。")
            self.store.write("settings.json", {**old, "selected": selected, "timezone": timezone, "context": context, "relay": relay})

    def node(self):
        selected = self.store.settings()["selected"]
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
        relay = {k: v for k, v in settings["relay"].items() if k != "downloads"}
        return fingerprint({"node": self.node(), "timezone": settings["timezone"], "context": settings["context"], "relay": relay, "recipe": self.recipe})

    def networks(self):
        for name, internal in ((self.internal, True), (self.external, False)):
            obj = self.docker.inspect("network", name)
            if not obj:
                args = ["network", "create", "--label", self.owner + "=" + self.store.instance]
                if internal:
                    args.append("--internal")
                self.docker.run(*args, name)
                obj = self.docker.inspect("network", name)
            self.owned(obj)
            if obj.get("Internal") != internal or obj.get("Driver") != "bridge" or obj.get("EnableIPv6"):
                raise SPXError("容器网络的隔离配置不一致。")
        config = self.docker.inspect("network", self.internal)["IPAM"]["Config"]
        subnet = next(ipaddress.ip_network(x["Subnet"]) for x in config if ":" not in x["Subnet"])
        return str(subnet[2]), str(subnet[3])

    def ensure_container(self, role, image, arguments, command=(), name=None):
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
            if not obj["State"]["Running"]:
                self.docker.run("start", name)
            return self.inspect(role, name)
        common = ["run", "-d", "--name", name, "--label", self.owner + "=" + self.store.instance, "--label", self.role + "=" + role, "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "512", "--env", "TZ=" + self.store.settings()["timezone"]]
        if role == "gateway":
            common += ["--label", STORAGE + "=" + storage]
        self.docker.run(*common, *arguments, image, *command)
        return self.inspect(role, name)

    def setup(self):
        ids = self.image_ids()
        gateway_ip, session_ip = self.networks()
        outbound = dict(self.node()["outbound"])
        from .proxy import loopback, validate_relay
        relay = validate_relay(self.store.settings()["relay"])
        forward_target = None
        extra = []
        if relay["enabled"]:
            if loopback(outbound["server"]):
                raise SPXError("启用本机线路中转时，落地节点请填写远端地址；本机代理填写到前置中转。")
            middle = dict(relay["outbound"])
            forward_target = {"host": middle["server"], "port": middle["server_port"]}
            middle.update({"tag": "host-line", "server": "127.0.0.1", "server_port": 2081})
            extra.append(middle)
            outbound["detour"] = "host-line"
        elif loopback(outbound["server"]) and outbound["type"] in ("socks", "http"):
            forward_target = {"host": outbound["server"], "port": outbound["server_port"]}
            outbound.update({"server": "127.0.0.1", "server_port": 2081})
        try:
            answers = socket.getaddrinfo(outbound["server"], outbound["server_port"], socket.AF_INET, socket.SOCK_STREAM)
            outbound["server"] = answers[0][4][0]
        except OSError as error:
            raise SPXError("本机无法解析节点的 IPv4 地址。") from error
        directory = self.store.home / "gateway"
        directory.mkdir(exist_ok=True)
        config = {"log": {"level": "warn"}, "inbounds": [{"type": "mixed", "tag": "clients", "listen": gateway_ip, "listen_port": 2080}], "outbounds": [outbound, *extra], "route": {"final": "selected"}}
        from .state import atomic_json
        atomic_json(directory / "config.json", config)
        atomic_json(directory / "lease.json", {"expires": time.time() + 300})
        gateway = self.ensure_container("gateway", ids["gateway"], ["--user", str(getattr(os, "getuid", lambda: 0)()), "--network", self.internal, "--ip", gateway_ip, "--read-only", "--tmpfs", "/tmp", "--mount", f"type=bind,source={directory},target=/config,readonly"], ["run", "-c", "/config/config.json"])
        if self.external not in gateway["NetworkSettings"]["Networks"]:
            self.docker.run("network", "connect", "--gw-priority", "1", self.external, gateway["Id"])
        session = self.ensure_container("session", ids["work"], ["--network", self.internal, "--ip", session_ip, "--dns", "127.0.0.1", "--read-only", "--tmpfs", "/tmp", "--memory", "128m"], ["sleep", "infinity"])
        self.store.write("environment.json", {"timezone": self.store.settings()["timezone"]})
        return {"gateway": gateway["Id"], "session": session["Id"], "proxy": f"http://{gateway_ip}:2080", "config_hash": fingerprint(config), "forward_target": forward_target}

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

    def probe(self, state):
        output = self.docker.run("run", "--rm", "--network", "container:" + state["session"], "--cap-drop", "ALL", "--security-opt", "no-new-privileges", self.image_ids()["work"], "python3", self.runtime_path("work", "probe.py"), state["proxy"], timeout=80)
        try:
            result = json.loads(output)
            ipaddress.IPv4Address(result["ip"])
            if result.get("direct_blocked") is not True:
                raise ValueError("direct connection allowed")
            return result
        except (ValueError, KeyError) as error:
            raise SPXError("出口核对或直连阻断检查未通过。") from error

    def check(self):
        with self.store.lock():
            self.doctor()
            self._stop("正在检查连接。")
            try:
                self.take_over_legacy_guard()
                state = self.setup()
                state.update({"phase": "checking", "policy": self.policy()})
                self.store.write("runtime.json", state)
                self.ensure_forward(state)
                self.log("通过所选节点核对两个出口来源，并检查容器直连是否被阻断…")
                evidence = self.probe(state)
                state.update({"phase": "review", "policy": self.policy(), "checked": time.time(), "evidence": evidence})
                self.store.write("runtime.json", state)
                return evidence
            except Exception:
                self._stop("连接检查失败，环境已停止。")
                raise

    def take_over_legacy_guard(self):
        if not self.store.legacy or self.store.read("controller.json", {}).get("app") == "enge-spx":
            return
        # The previous controller wakes every 30 seconds. Keep the state stopped
        # until it releases its guard lock, so it cannot stop a newly confirmed
        # SPX connection using the old policy fingerprint.
        self.log("正在接管旧版后台监测，最长约 40 秒；原有数据会保留。")
        deadline = time.monotonic() + 40
        while True:
            try:
                with self.store.lock("guard"):
                    self.store.write("controller.json", {"app": "enge-spx"})
                return
            except SPXError:
                if time.monotonic() >= deadline:
                    raise SPXError("旧版后台监测尚未退出，请先退出旧版程序，再重新检查连接。")
                time.sleep(.2)

    def audit_topology(self, state):
        session, gateway = self.inspect("session"), self.inspect("gateway")
        if not session or not gateway or session["Id"] != state["session"] or gateway["Id"] != state["gateway"] or not session["State"]["Running"] or not gateway["State"]["Running"]:
            raise SPXError("容器已停止或重新创建，请重新检查和确认连接。")
        if set(session["NetworkSettings"]["Networks"]) != {self.internal} or set(gateway["NetworkSettings"]["Networks"]) != {self.internal, self.external}:
            raise SPXError("检测到容器网络发生变化。")
        if not self.owned(self.docker.inspect("network", self.internal)).get("Internal"):
            raise SPXError("内部网络隔离已改变。")
        config = self.store.read("gateway/config.json")
        if fingerprint(config) != state["config_hash"] or self.policy() != state["policy"]:
            raise SPXError("节点或运行配置已改变，请重新检查。")
        if state.get("forward_target"):
            forward = self.store.read("forward.json", {})
            if forward.get("gateway") != state["gateway"] or forward.get("policy") != state["policy"] or time.time() - forward.get("heartbeat", 0) > 12:
                raise SPXError("本机线路中转已断开，请重新检查连接。")
        for name in self.managed():
            obj = self.docker.inspect("container", name)
            self.owned(obj)
            role = obj["Config"]["Labels"][self.role]
            if role in ("project", "browser") and obj["HostConfig"]["NetworkMode"] != "container:" + state["session"]:
                raise SPXError("工作容器的网络空间已改变。")

    def confirm(self):
        with self.store.lock():
            state = self.store.read("runtime.json", {})
            try:
                if state.get("phase") != "review" or time.time() - state["checked"] > 300:
                    raise SPXError("检查结果已过期，请重新检查节点。")
                self.audit_topology(state)
                evidence = self.probe(state)
                if evidence["ip"] != state["evidence"]["ip"]:
                    raise SPXError("复核时出口 IP 已改变，请重新检查和核对。")
                state.update({"phase": "ready", "evidence": evidence, "heartbeat": time.time(), "confirmed": time.time(), "browser_token": secrets.token_hex(32)})
                self.store.write("gateway/lease.json", {"expires": time.time() + 180})
                self.store.write("runtime.json", state)
                self.start_guard()
                return evidence
            except Exception:
                self._stop("连接尚未确认，环境已停止。")
                raise

    def background(self, action):
        args = ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "enge_spx"])
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
        with (self.store.home / (action + ".log")).open("a", encoding="utf-8") as log:
            subprocess.Popen([*args, "--data", str(self.store.home), action], stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=os.environ.copy(), cwd=str(Path(__file__).resolve().parent.parent), creationflags=flags, start_new_session=os.name != "nt")

    def start_guard(self):
        self.background("guard")

    def ready(self):
        state = self.store.read("runtime.json", {})
        if state.get("phase") != "ready":
            raise SPXError("请先检查节点、核对出口 IP 并确认连接。")
        try:
            self.audit_topology(state)
            if time.time() - state.get("heartbeat", 0) > 100:
                raise SPXError("连接监测进程已失联，请重新检查连接。")
            result = self.probe(state)
            if result["ip"] != state["evidence"]["ip"]:
                raise SPXError("检测到出口 IP 改变，环境已停止。")
            state["heartbeat"] = time.time()
            self.store.write("gateway/lease.json", {"expires": time.time() + 180})
            self.store.write("runtime.json", state)
            return state
        except Exception:
            self._stop("连接监测未通过，请重新检查节点。")
            raise

    def guard(self):
        try:
            with self.store.lock("guard"):
                while self.store.read("runtime.json", {}).get("phase") == "ready":
                    try:
                        with self.store.lock():
                            self.ready()
                    except SPXError:
                        if self.store.read("runtime.json", {}).get("phase") != "ready":
                            break
                    time.sleep(30)
        except SPXError:
            pass

    def managed(self):
        return self.docker.run("ps", "-aq", "--filter", "label=" + self.owner + "=" + self.store.instance).splitlines()

    def _stop(self, reason="环境已停止，账号和项目数据已保留。"):
        self.store.write("runtime.json", {"phase": "stopped", "reason": reason})
        self.store.write("gateway/lease.json", {"expires": 0})
        if not self.docker.executable or not self.store.read("images.json"):
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

    def stop(self):
        with self.store.lock():
            self._stop()

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
        if self.store.legacy:
            result += ["--env", LEGACY_BROWSER_TOKEN + "=" + state["browser_token"]]
        return [*result, "--env", "NO_PROXY=localhost,127.0.0.1,::1", "--env", "no_proxy=localhost,127.0.0.1,::1", "--env", "SPX_BROWSER_TOKEN=" + state["browser_token"], "--env", "BROWSER=/usr/local/bin/xdg-open", "--env", "TZ=" + self.store.settings()["timezone"]]

    def _browser(self, state):
        ids = self.image_ids()
        # A stopped browser may contain an old one-time display token. Replace its
        # container, keeping its profile and downloads in dedicated persistent volumes.
        old = self.inspect("browser")
        if old and not old["State"]["Running"]:
            self.docker.run("rm", old["Id"])
        obj = self.ensure_container("browser", ids["browser"], ["--network", "container:" + state["session"], "--shm-size", "512m", "--memory", "2g", "--volume", self.prefix + "-browser-home:/home/workspace", "--volume", self.prefix + "-downloads:/home/workspace/Downloads", *self.proxy_env(state)])
        for _ in range(40):
            try:
                self.docker.run("exec", obj["Id"], "python3", "-c", "import socket; socket.create_connection(('127.0.0.1',5900),.3).close(); socket.create_connection(('127.0.0.1',6081),.3).close()", timeout=3)
                break
            except SPXError:
                if not self.inspect("browser")["State"]["Running"]:
                    raise SPXError("共享浏览器启动失败，请检查此实例 browser 容器的日志。")
                time.sleep(.5)
        else:
            raise SPXError("共享浏览器启动超时，请重试。")
        self.viewer_assets(obj)
        descriptor = self.display_relay(obj, state)
        token = urllib.parse.quote("websockify?token=" + state["browser_token"], safe="")
        return descriptor["origin"] + f"/vnc.html?autoconnect=true&resize=scale&path={token}"

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

    def browser(self):
        with self.store.lock():
            state = self.ready()
            url = self._browser(state)
        webbrowser.open(url)
        return url

    def _project(self, path, state):
        directory, key = self.store.project(path)
        name = self.prefix + "-project-" + key
        ids = self.image_ids()
        obj = self.ensure_container("project", ids["work"], ["--network", "container:" + state["session"], "--memory", "4g", "--mount", f"type=bind,source={directory},target=/workspace/{key}", "--volume", self.prefix + "-tools-home:/home/workspace", "--workdir", "/workspace/" + key, *self.proxy_env(state)], name=name)
        settings = self.store.settings()
        settings["projects"] = list(dict.fromkeys([*settings["projects"], str(directory)]))
        self.store.write("settings.json", settings)
        return obj, key

    def tool_command(self, path, command, interactive=True):
        with self.store.lock():
            state = self.ready()
            self._browser(state)
            obj, key = self._project(path, state)
            flags = ["-it"] if interactive else ["-i"]
            return self.docker.command("exec", *flags, "--workdir", "/workspace/" + key, *self.proxy_env(state), obj["Id"], *command)

    def terminal(self, path, tool):
        from .terminal import launch, resolve
        commands = {"claude": ["claude"], "codex": ["codex"], "shell": ["bash", "-l"], "login-claude": ["claude", "auth", "login"], "login-codex": ["codex", "login"]}
        if tool not in commands:
            raise SPXError("未知工具。")
        if os.name != "nt":
            raise SPXError("此按钮在 Windows 中打开终端；其他系统请使用命令行入口。")
        config = self.store.settings()["terminal"]
        resolve(config)
        command = self.tool_command(path, commands[tool])
        directory, _ = self.store.project(path)
        launch(config, command, str(directory), "ENGE SPX · " + tool, self.docker.environment())
        # Open the viewer so any account authorization URL stays in Chromium.
        self.browser()

    def status(self):
        return status_snapshot(self.store)
