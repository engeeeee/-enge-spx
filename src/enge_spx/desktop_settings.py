"""Read only the backend selection needed for an offline WSL2 stop proof.

Docker stores user overrides, not necessarily its WSL2 default. Resolve known
user/admin/install layers without changing them. An implicit WSL2 selection
still requires independent version-2 registration and complete stopped proof.
"""
from dataclasses import dataclass
import ctypes
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Backend:
    enabled: bool
    reason: str
    implicit: bool = False


class InvalidSettings(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSettings("duplicate_keys")
        result[key] = value
    return result


def _constant(value):
    raise InvalidSettings("invalid_json_constant")


def _read(path):
    try:
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
    except FileNotFoundError:
        return None
    if len(raw) > 1024 * 1024:
        raise InvalidSettings("oversized_settings")
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(data, dict):
        raise InvalidSettings("invalid_object")
    return data


def _folder(variable, csidl):
    raw = os.environ.get(variable)
    if raw and Path(raw).is_absolute():
        return Path(raw)
    if os.name != "nt":
        return None
    from ctypes import wintypes as w
    shell = ctypes.WinDLL("shell32", use_last_error=True, winmode=0x00000800)
    shell.SHGetFolderPathW.argtypes = [w.HWND, ctypes.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
    shell.SHGetFolderPathW.restype = w.LONG
    buffer = ctypes.create_unicode_buffer(32768)
    # Current user's actual folder; never create a folder or use another user.
    if shell.SHGetFolderPathW(None, csidl, None, 0, buffer) != 0:
        return None
    path = Path(buffer.value)
    return path if path.is_absolute() else None


def _fields(data, name):
    groups = [data]
    for key, value in data.items():
        if key.casefold() == "linuxvm":
            if not isinstance(value, dict):
                raise InvalidSettings("invalid_linuxvm")
            groups.append(value)
    return [value for group in groups for key, value in group.items() if key.casefold() == name.casefold()]


def _boolean(data, name):
    values = _fields(data, name)
    decoded = []
    locks = []
    for value in values:
        if isinstance(value, dict):
            lock = value.get("locked", False)
            if type(lock) is not bool:
                raise InvalidSettings("invalid_lock")
            locks.append(lock)
            value = value.get("value")
        else:
            locks.append(False)
        if type(value) is not bool:
            raise InvalidSettings("invalid_boolean")
        decoded.append(value)
    if len(set(decoded)) > 1 or len(set(locks)) > 1:
        raise InvalidSettings("conflicting_values")
    return (decoded[0], locks[0]) if decoded else (None, False)


def _backend_hint(data):
    other = False
    for name in ("useWindowsContainers", "useDockerVmm", "dockerVmmEnabled"):
        value, _ = _boolean(data, name)
        other |= value is True
    choices = []
    for name in ("backend", "defaultBackend", "virtualMachineManager"):
        for raw in _fields(data, name):
            value = raw.get("value") if isinstance(raw, dict) else raw
            if not isinstance(value, str) or not value.strip():
                raise InvalidSettings("invalid_backend")
            choices.append(value.strip().casefold() in ("wsl", "wsl-2", "wsl2"))
    if len(set(choices)) > 1:
        raise InvalidSettings("conflicting_backends")
    return False if other else choices[0] if choices else None


def resolve(user, admin=None, install=None):
    """Resolve known layers; reject policy conflicts whose activation is unknown.

    Non-WSL user VMM/Windows selection is a veto, even with a stale WSL flag.
    No inference is made from malformed or conflicting values.
    """
    admin, install = admin or {}, install or {}
    user_value, _ = _boolean(user, "wslEngineEnabled")
    policy, locked = _boolean(admin, "wslEngineEnabled")
    installed, _ = _boolean(install, "wslEngineEnabled")
    hint = _backend_hint(user)
    if hint is False:
        return Backend(False, "other_backend_selected")
    if _backend_hint(admin) is False:
        return Backend(False, "other_policy_backend")
    if locked and policy is not None:
        if user_value is not None and user_value != policy:
            return Backend(False, "conflicting_policy")
        if user_value is None and policy is True and (installed is False or installed is None and _backend_hint(install) is False):
            return Backend(False, "conflicting_policy")
        return Backend(policy, "locked_policy" if policy else "policy_disabled", user_value is None)
    if user_value is not None:
        return Backend(user_value, "explicit_user" if user_value else "user_disabled")
    if hint is True:
        return Backend(True, "user_backend_wsl2", True)
    if policy is not None:
        if policy is True and (installed is False or installed is None and _backend_hint(install) is False):
            return Backend(False, "conflicting_policy")
        return Backend(policy, "policy_default" if policy else "policy_disabled", True)
    if installed is not None:
        return Backend(installed, "install_default" if installed else "install_disabled", True)
    hint = _backend_hint(install)
    if hint is not None:
        return Backend(hint, "install_backend_wsl2" if hint else "other_install_backend", True)
    return Backend(True, "default_wsl2", True)


def configuration():
    stage = "user"
    try:
        roaming = _folder("APPDATA", 26)
        if roaming is None:
            return Backend(False, "profile_directory_unavailable")
        user = None
        for name in ("settings-store.json", "settings.json"):
            user = _read(roaming / "Docker" / name)
            if user is not None:
                break  # Never substitute stale legacy settings for current data.
        if user is None:
            return Backend(False, "user_settings_missing")
        stage = "machine"
        common = _folder("ProgramData", 35)
        if common is None:
            return Backend(False, "machine_directory_unavailable")
        stage = "admin"
        admin = _read(common / "DockerDesktop/admin-settings.json")
        stage = "install"
        install = _read(common / "DockerDesktop/install-settings.json")
        stage = "values"
        return resolve(user, admin, install)
    except InvalidSettings as error:
        return Backend(False, str(error))  # Only fixed codes created above.
    except PermissionError:
        return Backend(False, stage + "_settings_denied")
    except (OSError, ValueError, TypeError, AttributeError):
        return Backend(False, stage + "_settings_unavailable")
