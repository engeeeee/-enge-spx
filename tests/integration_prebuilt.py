"""Install the exported release archive through the actual download/import path."""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import uuid

from enge_spx import downloads, __version__
from enge_spx.engine import Docker, Engine
from enge_spx.state import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="default")
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    meta = json.loads((args.directory / f"ENGE-SPX-Runtime-linux-amd64-{__version__}.json").read_text())
    docker = Docker(args.context)
    resolved = {}
    for role, identifier in meta["images"].items():
        image = docker.inspect("image", identifier) or docker.inspect("image", meta["image_configs"][role])
        if image:
            resolved[role] = image["Id"]
    name = "spx-bundle-test-" + uuid.uuid4().hex[:12]
    tag = name + ":preserve"
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(args.directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if len(resolved) != 3:
            docker.run("load", "--input", str(args.directory / meta["filename"]), timeout=1200)
            for role, identifier in meta["images"].items():
                resolved[role] = (docker.inspect("image", identifier) or docker.inspect("image", meta["image_configs"][role]))["Id"]
        docker.run("tag", resolved["work"], tag)
        docker.run("run", "--name", name, "--network", "none", "--entrypoint", "sh", tag, "-c", "printf preserved > /tmp/spx-preserved")
        existing = docker.inspect("container", name)["Id"]
        with tempfile.TemporaryDirectory() as private:
            store = Store(Path(private))
            settings = store.settings()
            store.write("settings.json", {**settings, "context": args.context})
            engine = Engine(store)
            stages = []
            with patch.object(downloads, "RELEASE", f"http://127.0.0.1:{server.server_port}/"):
                engine.install_prebuilt(lambda value: stages.append(value["stage"]))
            assert engine.image_ids() == resolved
            assert all(stage in stages for stage in ("manifest", "download", "verify", "import", "done"))
            # Repeat installation must use verified local images without any network.
            with patch.object(downloads, "client", side_effect=AssertionError("Unexpected repeat download")):
                engine.install_prebuilt()
            assert docker.inspect("image", tag)["Id"] == resolved["work"]
            assert docker.inspect("container", name)["Id"] == existing
            # Inspect the existing writable layer without starting a replacement.
            docker.run("cp", name + ":/tmp/spx-preserved", str(Path(private) / "preserved"))
            assert (Path(private) / "preserved").read_text() == "preserved"
        print("PASS: verified archive download, Docker import, repeat install, existing tags and container data")
    finally:
        server.shutdown()
        server.server_close()
        if docker.inspect("container", name):
            docker.run("rm", "-f", name)
        if docker.inspect("image", tag):
            docker.run("image", "rm", tag)


if __name__ == "__main__":
    main()
