"""Exercise actual DPAPI migration/export through the frozen Windows CLI."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="spx-frozen-dpapi-") as folder:
        home = Path(folder) / "private"
        home.mkdir()
        node = {"id": "preserved", "label": "Frozen DPAPI fixture", "outbound": {"type": "socks", "server": "192.0.2.1", "server_port": 1080, "username": "fixture", "password": "synthetic-frozen-fixture-only"}}
        (home / "nodes.json").write_text(json.dumps([node]), encoding="utf-8")
        (home / "settings.json").write_text(json.dumps({"selected": "preserved"}), encoding="utf-8")
        def run(*arguments):
            result = subprocess.run([str(executable), "--data", str(home), "credentials", *arguments], capture_output=True, text=True, encoding="utf-8", timeout=30)
            if result.returncode or node["outbound"]["password"] in result.stdout + result.stderr:
                raise RuntimeError("Frozen credential operation failed or exposed its synthetic secret")
            return json.loads(result.stdout)
        migrated = run("migrate")
        assert migrated["encrypted"] and migrated["mode"] == "dpapi-current-user"
        encrypted = (home / "nodes.json").read_bytes()
        assert json.loads(encrypted)["format"] == "enge-spx-dpapi-json"
        assert node["outbound"]["password"].encode() not in encrypted
        assert not run("status")["pending"]
        target = Path(folder) / "explicit-rollback"
        run("export-legacy", "--output", str(target), "--allow-plaintext")
        assert json.loads((target / "nodes.json").read_text(encoding="utf-8")) == [node]
        assert json.loads((target / "settings.json").read_text(encoding="utf-8"))["selected"] == "preserved"
        assert (home / "nodes.json").read_bytes() == encrypted
        run("clear-proxies")
        empty = Path(folder) / "cleared-check"
        run("export-legacy", "--output", str(empty), "--allow-plaintext")
        assert json.loads((empty / "nodes.json").read_text(encoding="utf-8")) == []
    print("Frozen Windows DPAPI migration, private explicit rollback and proxy deletion verified")


if __name__ == "__main__":
    main()
