"""Browser-only container restrictions and verifiable sandbox evidence."""
import json

from .brand import CONTAINERS
from .state import SPXError

PROFILE = CONTAINERS / "browser-seccomp.json"


def arguments():
    return ["--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--security-opt", "seccomp=" + str(PROFILE)]


def _security_options(options):
    """Docker accepts both key=value and legacy key:value security options.

    Split at the first separator, before the JSON payload, which can contain
    either character itself. Keep duplicates so a later false/unconfined option
    cannot be hidden by an earlier safe value.
    """
    parsed = {}
    if not isinstance(options, list) or any(not isinstance(value, str) for value in options):
        return parsed
    for option in options:
        key, separator, value = option.partition("=")
        if ":" in key:
            key, separator, value = option.partition(":")
        parsed.setdefault(key, []).append(value if separator else None)
    return parsed


def validate_container(obj):
    config = obj.get("Config") or {}
    host = obj.get("HostConfig") or {}
    opts = _security_options(host.get("SecurityOpt"))
    profiles = opts.get("seccomp", [])
    expected = json.loads(PROFILE.read_text(encoding="utf-8"))
    profile_ok = False
    if len(profiles) == 1 and profiles[0] is not None:
        try:
            profile_ok = json.loads(profiles[0]) == expected
        except ValueError:
            profile_ok = profiles[0] == str(PROFILE)
    no_new_privileges = opts.get("no-new-privileges", [])
    checks = {
        "User=1000": str(config.get("User", "")).split(":")[0] == "1000",
        "Privileged=false": host.get("Privileged") is False,
        "CapAdd=空": not host.get("CapAdd"),
        "CapDrop=ALL": "ALL" in {str(v).upper() for v in host.get("CapDrop") or []},
        "ReadonlyRootfs=true": host.get("ReadonlyRootfs") is True,
        "no-new-privileges=true": bool(no_new_privileges) and all(value in (None, "true") for value in no_new_privileges),
        "seccomp=应用专用策略": profile_ok,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        # Only fixed check names are safe to expose; never dump inspect, paths,
        # environment variables, tokens or a raw security-option value.
        raise SPXError("浏览器容器安全检查未通过：" + "、".join(failed) + "。请停止环境并重试；不会使用无沙箱模式。")
    if host.get("PidMode") not in (None, "", "private") or host.get("IpcMode") not in (None, "", "private") or host.get("Devices") or host.get("DeviceRequests") or any(item.get("Type") == "bind" or item.get("Type") == "volume" and item.get("Destination") not in ("/home/workspace", "/home/workspace/Downloads") for item in obj.get("Mounts", [])):
        raise SPXError("浏览器存在非预期的宿主 namespace、设备或文件挂载，入口已拒绝。")


def validate_status(value):
    keys = ("namespace", "pid_namespace", "network_namespace", "seccomp_bpf")
    renderer_keys = ("non_root", "no_new_privileges", "no_capabilities", "seccomp", "additional_seccomp_filter", "nested_pid_namespace")
    if value.get("schema") != 1 or any(value.get(key) is not True for key in keys) or any((value.get("renderer") or {}).get(key) is not True for key in renderer_keys):
        raise SPXError("Chromium 沙箱状态未通过验证；浏览器入口已阻止，请检查内核 user namespaces、Docker seccomp 和 LSM 限制。")
    return value
