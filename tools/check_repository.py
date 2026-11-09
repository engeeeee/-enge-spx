"""Check release identity, About configuration and local documentation links."""
import ast
import json
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from enge_spx import __version__
from enge_spx.brand import REPOSITORY


def main():
    errors = []
    metadata = json.loads((ROOT / ".github/repository.json").read_text(encoding="utf-8"))
    if metadata["repository"] != REPOSITORY or not 1 <= len(metadata["description"]) <= 350:
        errors.append("About configuration does not match the current repository")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project["urls"]["Homepage"] != "https://github.com/" + REPOSITORY:
        errors.append("Package homepage does not match the repository")
    for name in ("packaging/windows/version-info.txt", "packaging/windows/cli-version-info.txt"):
        text = (ROOT / name).read_text(encoding="utf-8")
        if "'FileVersion', '" + __version__ + "'" not in text:
            errors.append(name + ": string version mismatch")
        match = re.search(r"filevers=(\([^)]*\))", text)
        if not match or ast.literal_eval(match[1]) != (*map(int, __version__.split(".")), 0):
            errors.append(name + ": numeric version mismatch")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for prefix in ("ENGE-SPX-Windows-x64-", "ENGE-SPX-Runtime-", "ENGE-SPX-UI-"):
        for version in re.findall(re.escape(prefix) + r"(\d+\.\d+\.\d+)", workflow):
            if version != __version__:
                errors.append("CI artifact version mismatch: " + version)
    installer = (ROOT / "packaging/windows/Installer.iss").read_text(encoding="utf-8")
    if '#define AppVersion "' + __version__ + '"' not in installer:
        errors.append("Installer default version mismatch")

    documents = [*ROOT.glob("*.md"), *ROOT.joinpath("docs").rglob("*.md")]
    for document in documents:
        text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
        for raw in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", text):
            target = urlsplit(raw.strip("<>"))
            if target.scheme or target.netloc or not target.path:
                continue
            resolved = (document.parent / unquote(target.path)).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f"{document.relative_to(ROOT)}: missing local link {raw}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Repository metadata, release versions and {len(documents)} documents checked")


if __name__ == "__main__":
    main()
