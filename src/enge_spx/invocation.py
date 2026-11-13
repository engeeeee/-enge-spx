"""Public console entry used by third-party terminal launchers."""
from pathlib import Path
import sys

from .state import SPXError


def console_entry():
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("spx.exe")
        if not executable.is_file():
            raise SPXError("缺少 spx.exe 命令行入口，请完整解压或安装 ENGE SPX。")
        return [str(executable)]
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return [str(executable), "-m", "enge_spx"]


def console_environment(docker_executable=None):
    from .docker_env import environment
    result = environment(docker_executable)
    # Source-mode attach starts with cwd=the authorized project. Never import
    # host modules from that untrusted cwd or a relative inherited PYTHONPATH.
    result["PYTHONSAFEPATH"] = "1"
    result["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    return result
