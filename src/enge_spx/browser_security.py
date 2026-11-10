"""Browser-only container restrictions and verifiable sandbox evidence."""
import json

from .brand import CONTAINERS
from .state import SPXError

PROFILE = CONTAINERS / "browser-seccomp.json"


def arguments():
    return ["--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--security-opt", "seccomp=" + str(PROFILE)]


def validate_container(obj):
    config = obj.get("Config") or {}
    host = obj.get("HostConfig") or {}
    opts = host.get("SecurityOpt") or []
    profiles = [value.split("=", 1)[1] for value in opts if value.startswith("seccomp=")]
    expected = json.loads(PROFILE.read_text(encoding="utf-8"))
    profile_ok = False
    if len(profiles) == 1:
        try:
            profile_ok = json.loads(profiles[0]) == expected
        except ValueError:
            profile_ok = profiles[0] == str(PROFILE)
    good = str(config.get("User", "")).split(":")[0] == "1000" and not host.get("Privileged") and not host.get("CapAdd") and "ALL" in {str(v).upper() for v in host.get("CapDrop", [])} and host.get("ReadonlyRootfs") and any(value in ("no-new-privileges", "no-new-privileges=true") for value in opts) and profile_ok
    if not good:
        raise SPXError("浏览器容器权限或 seccomp 策略不符合安全要求，请停止环境并重新准备；不会使用无沙箱模式。")


def validate_status(value):
    keys = ("namespace", "pid_namespace", "network_namespace", "seccomp_bpf")
    renderer_keys = ("non_root", "no_new_privileges", "no_capabilities", "seccomp", "additional_seccomp_filter", "nested_pid_namespace")
    if value.get("schema") != 1 or any(value.get(key) is not True for key in keys) or any((value.get("renderer") or {}).get(key) is not True for key in renderer_keys):
        raise SPXError("Chromium 沙箱状态未通过验证；浏览器入口已阻止，请检查内核 user namespaces、Docker seccomp 和 LSM 限制。")
    return value
