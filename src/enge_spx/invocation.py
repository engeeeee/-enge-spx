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
