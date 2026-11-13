"""Actual Docker clipboard transport checks used by the existing integrations."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import zlib
import struct

from enge_spx.brand import PACKAGE_RESOURCES
from enge_spx.clipboard import Snapshot
from enge_spx.clipboard_transfer import Transfer
from enge_spx.state import SPXError
from enge_spx.workspace_profiles import project_plan


def synthetic_png():
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 24, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + b"\xd9\x77\x57" * 32) * 24)) + chunk(b"IEND", b"")


def verify_protected_transfer(engine, project, worker, state):
    original = engine.docker.inspect("container", worker["Id"])
    with tempfile.TemporaryDirectory(prefix="spx-clipboard-source-") as tmp:
        source = Path(tmp)
        values = {"截图-中文.png": synthetic_png(), "日志-🦄.txt": "first\r\n第二行".encode(), "code.py": b"print('synthetic')\n", "stream.bin": b"stream-fixture-" * 160000}
        for name, content in values.items():
            (source / name).write_bytes(content)
        # Project filenames must never become Python imports in the transfer.
        shadows = [project / name for name in ("json.py", "hashlib.py")]
        for shadow in shadows:
            assert not shadow.exists()
            shadow.write_text("raise RuntimeError('must not import project code during clipboard transfer')\n")
        transfer = Transfer(engine, str(project), "codex", state["session"], worker["Id"])
        try:
            frames = transfer.paste(Snapshot("files", tuple(str(source / name) for name in values)))
            paths = transfer.last_paths
            assert len(frames) == 5 and sum(transfer.last_images) == 1
            code = "import os,json,hashlib;from pathlib import Path;paths=" + repr(paths) + ";assert os.getuid()==1000;print(json.dumps([hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]))"
            actual = json.loads(engine.docker.run("exec", worker["Id"], "python3", "-I", "-c", code))
            assert actual == [hashlib.sha256(x).hexdigest() for x in values.values()]
            # The Linux runner uid may differ from container uid 1000. Keep
            # cache mode 0700/0600; verify bytes through the authorized container
            # and the already audited exact bind rather than widening modes.
            assert (project / ".enge-spx-clipboard").is_dir()
            assert not (project / "日志-🦄.txt").exists(), "source parent must not be mounted/copied wholesale"
            changed = engine.docker.inspect("container", worker["Id"])
            assert changed["Id"] == original["Id"]
            assert changed["HostConfig"] == original["HostConfig"]
            assert changed["Config"]["User"] == original["Config"]["User"]
            stale = Transfer(engine, str(project), "codex", "stale-session", worker["Id"])
            try:
                try:
                    stale.paste(Snapshot("files", (str(source / "code.py"),)))
                    raise AssertionError("stale session imported a clipboard file")
                except SPXError:
                    pass
            finally:
                stale.close()
            return {"files": len(paths), "stream_bytes": len(values["stream.bin"]), "hashes_match": True, "uid": 1000, "container_reused": True, "mounts_unchanged": True, "stale_session_rejected": True}
        finally:
            transfer.close()
            cleanup = "/workspace/" + transfer.plan["key"] + "/.enge-spx-clipboard/" + transfer.bridge
            code = "from pathlib import Path;import shutil;p=Path(" + repr(cleanup) + ");shutil.rmtree(p,ignore_errors=True)\ntry:p.parent.rmdir()\nexcept OSError:pass"
            engine.docker.run("exec", worker["Id"], "python3", "-I", "-c", code)
            for shadow in shadows:
                shadow.unlink(missing_ok=True)


def verify_readonly_import(engine, project, worker):
    plan = project_plan(engine, str(project))
    assert plan["access"] == "ro"
    original = engine.docker.inspect("container", worker["Id"])
    before = sorted(str(p.relative_to(project)) for p in project.rglob("*"))
    content = b"read-only project clipboard fixture"
    name, bridge = secrets.token_hex(16) + ".txt", secrets.token_hex(16)
    header = {"schema": 1, "project": plan["key"], "access": "ro", "bridge": bridge, "files": [{"name": name, "size": len(content)}], "prune": []}
    packet = json.dumps(header).encode() + b"\n" + content + hashlib.sha256(content).digest()
    script = (PACKAGE_RESOURCES / "checks/clipboard_transfer.py").read_text(encoding="utf-8")
    command = engine.docker.command("exec", "-i", "--workdir", "/workspace/" + plan["key"], worker["Id"], "python3", "-I", "-c", script)
    result = subprocess.run(command, input=packet, capture_output=True, timeout=20, env=engine.docker.environment())
    assert result.returncode == 0, "read-only clipboard importer failed"
    response = json.loads(result.stdout)
    path = response["paths"][0]
    assert path == "/tmp/enge-spx-clipboard-" + plan["key"] + "/" + bridge + "/" + name
    code = "import os,hashlib;from pathlib import Path;assert os.getuid()==1000;print(hashlib.sha256(Path(" + repr(path) + ").read_bytes()).hexdigest());assert not (Path('/home/workspace')/'enge-spx-clipboard').exists()"
    assert engine.docker.run("exec", worker["Id"], "python3", "-I", "-c", code) == hashlib.sha256(content).hexdigest()
    assert before == sorted(str(p.relative_to(project)) for p in project.rglob("*"))
    assert original["HostConfig"] == engine.docker.inspect("container", worker["Id"])["HostConfig"]
    return {"uid": 1000, "host_readonly_preserved": True, "private_tmp": True, "mounts_unchanged": True, "fixture_private_path": path}


def verify_native_api(engine, worker, destination):
    """Extract test tools, not account data; run native-host synthetic API test.

    This isolates CLI image serialization from transport/authorization tests.
    No user HOME or personal clipboard is read and no binary is published.
    """
    code = '''import json
from pathlib import Path
base=Path('/usr/local/lib/node_modules')
codex=next((base/'@openai/codex').rglob('bin/codex'))
claude=next(p for p in (base/'@anthropic-ai/claude-code').rglob('claude') if p.is_file() and p.stat().st_size>1000000)
print(json.dumps({'codex':str(codex.parent.parent),'claude':str(claude)}))
'''
    paths = json.loads(engine.docker.run("exec", worker["Id"], "python3", "-I", "-c", code))
    with tempfile.TemporaryDirectory(prefix="spx-native-cli-fixture-") as tmp:
        directory = Path(tmp)
        for key, source in paths.items():
            assert source.startswith("/usr/local/lib/node_modules/")
            engine.docker.run("cp", worker["Id"] + ":" + source, str(directory / key), timeout=60)
        output = directory / "native-api.json"
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("integration_cli_clipboard.py")),
                                 "--claude", str(directory / "claude"), "--codex", str(directory / "codex/bin/codex"),
                                 "--qt-terminal", "--capture-terminal", str(Path(destination).with_name("clipboard-terminal.png")),
                                 "--output", str(output)], env=os.environ.copy(), capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError("Native CLI/API clipboard fixture failed: " + result.stderr[-1800:])
        evidence = json.loads(output.read_text())
        Path(destination).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return evidence
