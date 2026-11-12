"""Publish an already-built static site through an atomic current symlink.

Configure the web server once, then retain old releases and hashed browser assets.
No deletion, process stop, DNS, TLS or web server configuration change is made.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import secrets
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/enge-spx"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "out"
    if not (source / "index.html").is_file():
        parser.error("Run npm run build first")
    base = args.root.resolve()
    (base / "releases").mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)
    release = base / "releases" / name
    current = base / "current"
    previous = current.resolve() if current.is_symlink() else None
    shutil.copytree(source, release)
    if previous and (previous / "_next/static").is_dir():
        for path in (previous / "_next/static").rglob("*"):
            if path.is_file():
                target = release / "_next/static" / path.relative_to(previous / "_next/static")
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
    for path in [release, *release.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    pending = base / ("next-" + name)
    pending.symlink_to(release)
    os.replace(pending, current)
    print("Published:", release)
    print("Previous:", previous or "none")


if __name__ == "__main__":
    main()
