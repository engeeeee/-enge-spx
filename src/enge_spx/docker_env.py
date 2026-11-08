"""Environment for the Docker CLI and its sibling credential helper programs."""
import os
from pathlib import Path


def environment(executable, source=None, windows=None):
    source = dict(os.environ if source is None else source)
    windows = os.name == "nt" if windows is None else windows
    excluded = {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}
    result = {key: value for key, value in source.items() if (key.upper() if windows else key) not in excluded}
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
    separator = ";" if windows else os.pathsep
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
