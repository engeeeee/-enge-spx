"""Windows terminal launchers. Child commands stay argv vectors, never cmd strings."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess

from .state import SPXError

PRESETS = {"自动（AI 智能粘贴）": "auto", "智能粘贴终端": "smart", "Windows Terminal": "wt", "PowerShell 7": "pwsh", "Windows PowerShell": "powershell", "自定义程序": "custom"}
DEFAULT_ARGUMENTS = "{command}"
# Read compatibility only: this old preset used fixed flags, regardless of its
# stored arguments. Normalize it into the same custom launcher as any other exe.
LEGACY_ARGUMENTS = '--working-directory "{project}" --title "{title}" --hold -e {command}'


def split_arguments(text: str) -> list[str]:
    """Parse Windows argv quoting (also testable without a Windows host)."""
    result, token, quoted, started, i = [], [], False, False, 0
    while i < len(text):
        char = text[i]
        if char in " \t" and not quoted:
            if started:
                result.append("".join(token))
                token, started = [], False
            i += 1
            continue
        started = True
        if char == "\\":
            end = i
            while end < len(text) and text[end] == "\\":
                end += 1
            count = end - i
            if end < len(text) and text[end] == '"':
                token.extend("\\" * (count // 2))
                if count % 2:
                    token.append('"')
                else:
                    quoted = not quoted
                i = end + 1
            else:
                token.extend("\\" * count)
                i = end
            continue
        if char == '"':
            if quoted and i + 1 < len(text) and text[i + 1] == '"':
                token.append('"')
                i += 2
                continue
            quoted = not quoted
        else:
            token.append(char)
        i += 1
    if quoted:
        raise SPXError("终端参数中的双引号没有闭合。")
    if started:
        result.append("".join(token))
    return result


def validate(config: dict | None) -> dict:
    config = config or {}
    kind = config.get("kind", "auto")
    if kind == "pebrel":
        config = {**config, "kind": "custom", "executable": config.get("executable") or discover("pebrel") or "pebrel.exe", "arguments": LEGACY_ARGUMENTS}
        kind = "custom"
    if kind not in PRESETS.values():
        raise SPXError("请选择受支持的终端，或选择自定义程序。")
    executable = str(config.get("executable", "")).strip().strip('"')
    arguments = str(config.get("arguments", DEFAULT_ARGUMENTS))
    if any(c in executable + arguments for c in "\r\n\0"):
        raise SPXError("终端程序和参数不能包含换行或空字符。")
    if kind == "custom":
        tokens = split_arguments(arguments)
        if tokens.count("{command}") != 1:
            raise SPXError("自定义参数必须包含一次独立的 {command}，用于插入工作区命令。")
        for token in tokens:
            if token != "{command}" and ("{" in token.replace("{project}", "").replace("{title}", "") or "}" in token.replace("{project}", "").replace("{title}", "")):
                raise SPXError("支持的参数占位符为 {project}、{title}、{command}。")
        if not executable:
            raise SPXError("请先选择第三方终端的 exe 程序。")
    return {"kind": kind, "executable": executable, "arguments": arguments}


def discover(kind: str) -> str | None:
    # The legacy name is only queried when reading a saved pre-0.8.4 preset.
    names = {"pebrel": "pebrel.exe", "wt": "wt.exe", "pwsh": "pwsh.exe", "powershell": "powershell.exe"}
    name = names[kind]
    found = shutil.which(name)
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local"))
    programs = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    roots = {"pebrel": [local / "Programs/Pebrel", programs / "Pebrel", local / "Microsoft/WindowsApps"], "wt": [local / "Microsoft/WindowsApps"], "pwsh": [programs / "PowerShell/7"], "powershell": [Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0"]}
    for root in roots[kind]:
        if (root / name).is_file():
            return str(root / name)
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                    candidate = winreg.QueryValue(key, None).strip('"')
                    if Path(candidate).is_file():
                        return candidate
            except OSError:
                pass
    return None


def resolve(config: dict | None) -> tuple[str, str]:
    config = validate(config)
    kind, executable = config["kind"], config["executable"]
    if kind == "smart":
        return kind, "ENGE SPX"
    if kind == "auto":
        for candidate in ("wt", "pwsh", "powershell"):
            found = discover(candidate)
            if found:
                return candidate, found
        raise SPXError("未找到可用终端，请在偏好设置中选择终端类型或自定义终端的 exe。")
    executable = os.path.expandvars(executable) if executable else discover(kind)
    if executable and not Path(executable).is_file():
        executable = shutil.which(executable)
    if not executable:
        raise SPXError("找不到所选终端，请选择它的 exe 文件；不会自动改用其他终端。")
    if Path(executable).suffix.lower() != ".exe":
        raise SPXError("请选择终端的 exe 文件，脚本和快捷方式不能作为终端程序。")
    return kind, executable


def launch_command(config: dict | None, command: list[str], project: str, title: str) -> tuple[list[str], int]:
    config = validate(config)
    kind, executable = resolve(config)
    if kind == "smart":
        return [*command, *(["--smart-terminal"] if "attach" in command else [])], getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if kind == "wt":
        # Semicolons are wt's own command separators, even inside quoted argv.
        if any(";" in arg for arg in [*command, project, title]):
            return [executable, "-w", "new", "new-tab", "--title", title.replace(";", "·"), *_powershell_command(command, project)], 0
        return [executable, "-w", "new", "new-tab", "--title", title, "-d", project, "--", *command], 0
    if kind in ("pwsh", "powershell"):
        return [executable, *_powershell_arguments(command)], getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    result = [executable]
    for token in split_arguments(config["arguments"]):
        if token == "{command}":
            result.extend(command)
        else:
            result.append(token.replace("{project}", project).replace("{title}", title))
    return result, 0


def _powershell_arguments(command: list[str], project: str | None = None) -> list[str]:
    quote = lambda value: "'" + value.replace("'", "''") + "'"
    script = "& " + " ".join(quote(arg) for arg in command)
    if project is not None:
        script = "Set-Location -LiteralPath " + quote(project) + "; " + script
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return ["-NoLogo", "-NoProfile", "-NoExit", "-EncodedCommand", encoded]


def _powershell_command(command: list[str], project: str) -> list[str]:
    executable = discover("powershell")
    if not executable:
        raise SPXError("此命令含 Windows Terminal 分隔符，需要 Windows PowerShell；也可选择自定义终端。")
    return [executable, *_powershell_arguments(command, project)]


def launch(config: dict | None, command: list[str], project: str, title: str, env=None):
    if os.name != "nt":
        raise SPXError("终端启动功能需要在 Windows 上使用。")
    argv, flags = launch_command(config, command, project, title)
    try:
        return subprocess.Popen(argv, cwd=project, env=env, creationflags=flags)
    except OSError as error:
        raise SPXError("终端启动失败，请检查程序路径和启动参数，可先点击“测试终端”。") from error


def test(config: dict | None, env=None):
    if validate(config)["kind"] == "smart":
        from .invocation import console_entry, console_environment
        return launch(config, [*console_entry(), "--terminal-preview"], str(Path.home()), "ENGE SPX · 终端测试", console_environment())
    shell = discover("powershell")
    if not shell:
        raise SPXError("未找到 Windows PowerShell，无法执行终端测试。")
    command = [shell, "-NoLogo", "-NoProfile", "-NoExit", "-Command", "Write-Host 'ENGE SPX: terminal connected.'; Write-Host 'Close this test window to continue.'"]
    return launch(config, command, str(Path.home()), "ENGE SPX · 终端测试", env)
