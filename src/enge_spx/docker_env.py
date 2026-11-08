"""Environment for the Docker CLI and its sibling credential helper programs."""
import os
from pathlib import Path


def desktop_application(executable=None):
    if os.name != "nt":
        return None
    roots = []
    if executable:
        # Custom-drive installations can be found from resources/bin/docker.exe.
        parent = Path(executable).resolve().parent
        roots += [parent, *list(parent.parents)[:3]]
    roots += [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop"]
    found = next((root / "Docker Desktop.exe" for root in roots if root.is_absolute() and (root / "Docker Desktop.exe").is_file()), None)
    if found:
        return found
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_name in (r"Software\Microsoft\Windows\CurrentVersion\App Paths\Docker Desktop.exe", r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop", r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DockerDesktop"):
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    raw = winreg.QueryValue(key, None) if "App Paths" in key_name else winreg.QueryValueEx(key, "InstallLocation")[0]
                candidate = Path(os.path.expandvars(str(raw).strip('"')))
                if "App Paths" not in key_name:
                    candidate /= "Docker Desktop.exe"
                if candidate.is_absolute() and candidate.is_file():
                    return candidate
            except OSError:
                pass
    return None


def environment(executable, source=None, windows=None):
    source = dict(os.environ if source is None else source)
    windows = os.name == "nt" if windows is None else windows
    excluded = {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}
    result = {key: value for key, value in source.items() if (key.upper() if windows else key) not in excluded}
    if not windows:
        return result
    path_keys = [key for key in result if (key.upper() if windows else key) == "PATH"]
    inherited = next((result[key] for key in path_keys if result[key]), "")
    for key in path_keys:
        del result[key]
    directories = [str(Path(executable).resolve().parent)] if executable else []
    if windows:
        values = {key.upper(): value for key, value in source.items()}
        roots = []
        if values.get("PROGRAMFILES"):
            roots.append(Path(values["PROGRAMFILES"]) / "Docker/Docker")
        if values.get("LOCALAPPDATA"):
            roots.append(Path(values["LOCALAPPDATA"]) / "Programs/DockerDesktop")
        directories += [str(root / "resources/bin") for root in roots if (root / "resources/bin").is_dir()]
    separator = ";"
    directories += inherited.split(separator)
    seen, paths = set(), []
    for directory in directories:
        if not directory:
            continue
        identity = directory.strip('"').rstrip("/\\")
        identity = identity.casefold() if windows else identity
        if identity not in seen:
            seen.add(identity)
            paths.append(directory)
    result["PATH"] = separator.join(paths)
    return result
