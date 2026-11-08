"""Export only verified images, without tags, for safe repeatable Docker import."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from enge_spx import __version__
from enge_spx.engine import Docker, Engine, RECIPE, image_recipe
from enge_spx.brand import LEGACY_LABEL_ROOT
from enge_spx.state import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="default")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    docker = Docker(args.context)
    with tempfile.TemporaryDirectory() as private:
        engine = Engine(Store(Path(private)))
        assert engine.recipes == report["recipes"]
    for role, identifier in report["images"].items():
        value = docker.inspect("image", identifier)
        assert value["Architecture"] == "amd64"
        assert image_recipe(value) == report["recipes"][role]
    args.output.mkdir(parents=True, exist_ok=True)
    filename = f"ENGE-SPX-Runtime-linux-amd64-{__version__}.tar.gz"
    archive = args.output / filename
    process = subprocess.Popen(docker.command("save", *report["images"].values()), stdout=subprocess.PIPE)
    with gzip.open(archive, "wb", compresslevel=1) as stream:
        while data := process.stdout.read(1024 * 1024):
            stream.write(data)
    assert process.wait() == 0
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    # Classic stores identify images by configuration digest; containerd uses the
    # OCI manifest. Preserve both exact identifiers from the verified archive.
    configs = {}
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            if not member.isfile() or member.size > 1024 * 1024 or member.size < 2:
                continue
            data = tar.extractfile(member).read()
            try:
                config = json.loads(data)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(config, dict) or "rootfs" not in config:
                continue
            labels = config.get("config", {}).get("Labels") or {}
            recipe = labels.get(RECIPE, labels.get(LEGACY_LABEL_ROOT + ".recipe"))
            for role, expected in report["recipes"].items():
                if recipe == expected:
                    configs[role] = "sha256:" + hashlib.sha256(data).hexdigest()
    assert set(configs) == set(report["images"])
    manifest = {"schema": 1, "version": __version__, "platform": "linux/amd64", "filename": filename, "bytes": archive.stat().st_size, "sha256": digest, "recipes": report["recipes"], "images": report["images"], "image_configs": configs}
    (args.output / filename.replace(".tar.gz", ".json")).write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output / (filename + ".sha256")).write_text(digest + "  " + filename + "\n")
    print(json.dumps({"filename": filename, "bytes": archive.stat().st_size, "sha256": digest}))


if __name__ == "__main__":
    main()
