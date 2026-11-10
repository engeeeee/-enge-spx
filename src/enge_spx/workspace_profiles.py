"""Versioned identity selection and exact data mounts; no account copying."""
from copy import deepcopy
import ntpath
import os
from pathlib import Path
import re
import stat

from .state import SPXError

FILE = "workspace-profiles.json"
PREVIOUS = "workspace-profiles-previous.json"
MARKER = "workspace-profiles-state.json"
PROFILE = "io.enge.spx.profile"
PROJECT = "io.enge.spx.project"
ACCESS = "io.enge.spx.project-access"
SHARED = "shared"


def defaults():
    return {"schema": 1, "selected": SHARED, "profiles": {SHARED: "默认共享（兼容旧版）"}, "projects": {}}


def profile_id(value):
    return isinstance(value, str) and (value == SHARED or re.fullmatch(r"[a-f0-9]{12}", value) is not None)


def display_name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 64 or any(ord(c) < 32 or ord(c) == 127 for c in value) or "://" in value:
        raise SPXError("身份名称需为 1–64 个可显示字符，不能包含链接或控制字符。")
    return value.strip()


def validate(value=None):
    if value is None:
        return defaults()
    if not isinstance(value, dict) or set(value) != {"schema", "selected", "profiles", "projects"} or type(value.get("schema")) is not int or value["schema"] != 1:
        raise SPXError("工作区身份配置版本或字段无效，已拒绝使用；不会回退到共享账号。")
    identities, projects = value["profiles"], value["projects"]
    if not isinstance(identities, dict) or not 1 <= len(identities) <= 64 or SHARED not in identities or not profile_id(value["selected"]) or value["selected"] not in identities:
        raise SPXError("工作区身份选择或列表无效；请恢复上次配置。")
    names = {}
    for key, name in identities.items():
        if not profile_id(key):
            raise SPXError("工作区身份标识无效。")
        names[key] = display_name(name)
    if len({name.casefold() for name in names.values()}) != len(names):
        raise SPXError("工作区身份名称不能重复。")
    if not isinstance(projects, dict) or len(projects) > 2000:
        raise SPXError("工作区项目授权列表无效。")
    for key, binding in projects.items():
        if not isinstance(key, str) or re.fullmatch(r"[a-f0-9]{16}", key) is None or not isinstance(binding, dict) or set(binding) != {"profile", "access"} or not isinstance(binding["profile"], str) or binding["profile"] not in names or binding["access"] not in ("ro", "rw"):
            raise SPXError("项目绑定的身份或只读/读写授权无效。")
    return {"schema": 1, "selected": value["selected"], "profiles": names, "projects": deepcopy(projects)}


def load(store):
    # Missing is compatibility; an explicit null or an unknown schema is not.
    check_files(store, FILE, MARKER)
    marker = store.read(MARKER)
    if marker is not None and (not isinstance(marker, dict) or set(marker) != {"schema", "enabled"} or type(marker["schema"]) is not int or marker["schema"] != 1 or marker["enabled"] is not True):
        raise SPXError("工作区身份迁移记录无效，请恢复配置；不会回退到共享账号。")
    if marker is not None and not (store.home / FILE).is_file():
        raise SPXError("工作区身份配置丢失，请恢复上次配置；不会回退到共享账号。")
    value = store.read(FILE, defaults())
    if value is None:
        raise SPXError("工作区身份配置为空，已拒绝启动；不会使用共享账号替代。")
    return validate(value)


def check_files(store, *names):
    for name in names:
        path = store.home / name
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise SPXError("工作区身份配置包含链接，已拒绝使用。")
        try:
            info = path.stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
            raise SPXError("工作区身份配置类型或大小无效，原数据保留。")


def policy(config):
    return {"schema": 1, "selected": config["selected"], "projects": config["projects"]}


def volumes(engine, identity):
    if not profile_id(identity):
        raise SPXError("工作区身份标识无效。")
    base = engine.prefix if identity == SHARED else engine.prefix + "-profile-" + identity
    return {kind: base + "-" + kind for kind in ("tools-home", "browser-home", "downloads")}


def project_name(engine, identity, key, access):
    if not profile_id(identity) or not isinstance(key, str) or re.fullmatch(r"[a-f0-9]{16}", key) is None or access not in ("ro", "rw"):
        raise SPXError("项目容器的身份或授权标识无效。")
    middle = "" if identity == SHARED else "profile-" + identity + "-"
    return engine.prefix + "-project-" + middle + key + ("-ro" if access == "ro" else "")


def project_plan(engine, path, config=None):
    config = config or load(engine.store)
    directory, key = engine.store.project(path)
    binding = config["projects"].get(key)
    if binding is None:
        if config["selected"] != SHARED:
            raise SPXError("此项目尚未绑定当前身份。请先在项目工作区应用身份和只读/读写授权。")
        binding = {"profile": SHARED, "access": "rw"}
    if binding["profile"] != config["selected"]:
        raise SPXError("此项目绑定了另一身份，请先切换并重新检查、确认连接。")
    return {"directory": directory, "key": key, **binding, "name": project_name(engine, binding["profile"], key, binding["access"])}


def project_arguments(plan):
    mount = f"type=bind,source={plan['directory']},target=/workspace/{plan['key']}"
    if plan["access"] == "ro":
        mount += ",readonly,bind-recursive=readonly,bind-propagation=rprivate"
    return ["--label", PROFILE + "=" + plan["profile"], "--label", PROJECT + "=" + plan["key"], "--label", ACCESS + "=" + plan["access"], "--mount", mount]


def same_source(actual, expected):
    """Exact host path, or documented Desktop drive translations; no suffix match."""
    if not isinstance(actual, str):
        return False
    expected = str(expected)
    drive, tail = ntpath.splitdrive(expected)
    if re.fullmatch(r"[A-Za-z]:", drive):
        logical = ntpath.normcase(ntpath.normpath(expected))
        if ntpath.normcase(ntpath.normpath(actual)) == logical:
            return True
        translated = "/" + drive[0].lower() + "/" + tail.replace("\\", "/").lstrip("/")
        if actual.replace("\\", "/").casefold().rstrip("/") in {(root + translated).casefold().rstrip("/") for root in ("/run/desktop/mnt/host", "/host_mnt")}:
            return True
        if os.name == "nt":
            candidate = actual
            for root in ("/run/desktop/mnt/host/", "/host_mnt/"):
                normalized = actual.replace("\\", "/")
                if normalized.casefold().startswith(root) and re.match(r"[A-Za-z]/", normalized[len(root):]):
                    remainder = normalized[len(root):]
                    candidate = remainder[0] + ":/" + remainder[2:]
            candidate_drive, _ = ntpath.splitdrive(candidate)
            if candidate_drive.casefold() == drive.casefold():
                try:
                    # Windows may return an 8.3 alias for the same directory.
                    # File identity is stronger than accepting a path suffix.
                    return Path(candidate).samefile(Path(expected))
                except OSError:
                    pass
        return False
    return os.path.normcase(os.path.normpath(actual)) == os.path.normcase(os.path.normpath(expected))


def _volume(item, expected):
    return item.get("Type") == "volume" and item.get("Name") == expected and item.get("RW") is True


def validate_mounts(engine, obj, config=None, plan=None):
    config = config or load(engine.store)
    labels = (obj.get("Config") or {}).get("Labels") or {}
    role = labels.get(engine.role)
    identity = labels.get(PROFILE, SHARED)
    if not profile_id(identity) or (obj.get("State") or {}).get("Running") and identity not in config["profiles"]:
        raise SPXError("容器身份不在已配置列表中，已拒绝使用其账号资料。")
    running = (obj.get("State") or {}).get("Running") is True
    if running and identity != config["selected"]:
        raise SPXError("检测到其它身份的容器仍在运行，请停止环境后重试。")
    mounts = obj.get("Mounts")
    if not isinstance(mounts, list) or any(not isinstance(item, dict) for item in mounts):
        raise SPXError("无法核验工作区数据挂载，环境保持停止。")
    by_target = {item.get("Destination"): item for item in mounts}
    if len(by_target) != len(mounts):
        raise SPXError("工作区挂载目标重复。")
    expected = volumes(engine, identity)
    if role == "browser":
        if set(by_target) - {"/home/workspace", "/home/workspace/Downloads", "/tmp"} or not _volume(by_target.get("/home/workspace", {}), expected["browser-home"]) or not _volume(by_target.get("/home/workspace/Downloads", {}), expected["downloads"]):
            raise SPXError("浏览器资料或下载卷与所选身份不符，已拒绝继承其它身份。")
        if "/tmp" in by_target and by_target["/tmp"].get("Type") != "tmpfs":
            raise SPXError("浏览器临时目录不是隔离的内存挂载。")
        return
    if role != "project":
        return
    from .browser_security import _security_options
    host = obj.get("HostConfig") or {}
    privileges = _security_options(host.get("SecurityOpt")).get("no-new-privileges", [])
    if str((obj.get("Config") or {}).get("User", "")).split(":")[0] != "1000" or host.get("Privileged") is not False or host.get("CapAdd") or "ALL" not in {str(cap).upper() for cap in host.get("CapDrop") or []} or not privileges or any(value not in (None, "true") for value in privileges) or host.get("PidMode") not in (None, "", "private") or host.get("IpcMode") not in (None, "", "private") or host.get("Devices") or host.get("DeviceRequests"):
        raise SPXError("项目容器权限超出工作区要求，已拒绝启动。")
    name = str(obj.get("Name", "")).lstrip("/")
    key, access = labels.get(PROJECT), labels.get(ACCESS)
    if PROFILE not in labels:
        match = re.fullmatch(re.escape(engine.prefix) + r"-project-([a-f0-9]{16})", name)
        if not match:
            raise SPXError("旧项目容器名称无法识别，未使用其账号资料。")
        key, access = match[1], "rw"
    if name != project_name(engine, identity, key, access):
        raise SPXError("项目容器名称与身份授权不符。")
    binding = config["projects"].get(key, {"profile": SHARED, "access": "rw"})
    if running and binding != {"profile": identity, "access": access}:
        raise SPXError("运行项目与已保存的身份或目录权限不一致。")
    destination = "/workspace/" + key
    if set(by_target) != {"/home/workspace", destination} or not _volume(by_target["/home/workspace"], expected["tools-home"]):
        raise SPXError("项目账号卷或挂载范围与身份不符。")
    mount = by_target[destination]
    if mount.get("Type") != "bind" or mount.get("RW") is not (access == "rw"):
        raise SPXError("项目目录挂载权限与授权不符；不会回退到读写。")
    if access == "ro":
        declared = host.get("Mounts")
        declared = [m for m in declared if isinstance(m, dict) and m.get("Target") == destination] if isinstance(declared, list) else []
        if len(declared) != 1 or declared[0].get("ReadOnly") is not True or (declared[0].get("BindOptions") or {}).get("ReadOnlyForceRecursive") is not True:
            raise SPXError("项目递归只读条件未通过，已拒绝继续；不会放宽为读写。")
    if plan and (plan["profile"] != identity or plan["key"] != key or plan["access"] != access or not same_source(mount.get("Source"), plan["directory"])):
        raise SPXError("项目目录、身份或权限与所选工作区不符。")
