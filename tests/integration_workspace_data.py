"""Unprivileged network-none Docker fixtures for identity data and read-only mounts."""
import argparse
import errno
import json
from pathlib import Path
import tempfile

from enge_spx.engine import Engine
from enge_spx.state import Store, SPXError
from enge_spx import workspace_profiles as profiles

IDLE = "import signal,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); time.sleep(3600)"


def run(context, output):
    records = []
    def passed(message):
        records.append(message)
        print("PASS", message, flush=True)
    with tempfile.TemporaryDirectory(prefix="spx-profile-data-") as folder:
        root = Path(folder)
        store, other_store = Store(root / "data"), Store(root / "other")
        for item in (store, other_store):
            item.write("settings.json", {**item.settings(), "context": context})
        engine, other = Engine(store), Engine(other_store)
        tag = "spx-profile-data:" + store.instance
        identities = [profiles.SHARED]
        project = root / "project with spaces"
        project.mkdir(mode=0o777)
        project.chmod(0o777)
        try:
            if not engine.docker.inspect("image", "python:3.12-alpine"):
                engine.docker.run("pull", "python:3.12-alpine", timeout=300)
            recipe = 'FROM python:3.12-alpine\nRUN mkdir -p /home/workspace/Downloads && chown -R 1000:1000 /home/workspace\nENV HOME=/home/workspace\nUSER 1000:1000\nCMD ["python3","-u","-c",' + json.dumps(IDLE) + ']\n'
            engine.docker.run("build", "--network", "none", "-t", tag, "-", input_data=recipe, timeout=120)
            image = engine.docker.inspect("image", tag)["Id"]
            for item in (store, other_store):
                item.write("images.json", {role: image for role in ("gateway", "work", "browser")})
            # Only image-recipe lookup is replaced for this synthetic fixture.
            # Production image, sandbox and network checks run in the full CI.
            engine.image_ids = lambda: {role: image for role in ("gateway", "work", "browser")}
            outsider = other.ensure_container("project", image, ["--network", "none"])
            def prepare():
                session = engine.ensure_container("session", image, ["--network", "none", "--read-only"])
                with store.lock(timeout=45):
                    return engine._project(str(project), {"session": session["Id"], "proxy": "http://127.0.0.1:9"})[0]
            def execute(obj, code):
                return engine.docker.run("exec", obj["Id"], "python3", "-c", code)
            def save(obj, name):
                execute(obj, "from pathlib import Path; p=Path('/home/workspace'); (p/'.claude').mkdir(exist_ok=True); (p/'.codex').mkdir(exist_ok=True); (p/'.claude/credentials-sentinel').write_text(" + repr(name) + "); (p/'.codex/auth-sentinel').write_text(" + repr(name) + "); Path('/tmp/profile-layer').write_text(" + repr(name) + ")")
            def empty(obj):
                return execute(obj, "from pathlib import Path; print(not Path('/home/workspace/.claude/credentials-sentinel').exists() and not Path('/home/workspace/.codex/auth-sentinel').exists())") == "True"
            shared = prepare()
            save(shared, "shared")
            alpha = engine.create_workspace_profile("A")["profile"]
            beta = engine.create_workspace_profile("B")["profile"]
            identities += [alpha, beta]
            assert engine.docker.inspect("container", shared["Id"])["State"]["Running"]
            passed("creating identities keeps the existing shared session running and copies no account data")
            engine.configure_workspace(alpha, str(project), "ro")
            assert not engine.docker.inspect("container", shared["Id"])["State"]["Running"]
            assert other.docker.inspect("container", outsider["Id"])["State"]["Running"]
            first = prepare()
            assert first["Id"] != shared["Id"] and empty(first)
            save(first, "alpha")
            result = execute(first, "from pathlib import Path; import errno\ntry:\n Path.cwd().joinpath('must-not-write').write_text('bad'); print('WRITABLE')\nexcept OSError as e:\n print(e.errno)")
            assert result == str(errno.EROFS), result
            assert not (project / "must-not-write").exists()
            binding = next(m for m in first["HostConfig"]["Mounts"] if m["Target"].startswith("/workspace/"))
            assert binding["ReadOnly"] and binding["BindOptions"]["ReadOnlyForceRecursive"]
            passed("separate Claude/Codex HOME is empty initially; recursive read-only really blocks writes while account caches remain writable")
            engine.configure_workspace(beta, str(project), "rw")
            second = prepare()
            assert empty(second) and second["Id"] not in (shared["Id"], first["Id"])
            save(second, "beta")
            execute(second, "from pathlib import Path; Path.cwd().joinpath('explicit-rw').write_text('written')")
            assert (project / "explicit-rw").read_text() == "written"
            passed("another identity has no prior accounts and writes to the project only after explicit read-write authorization")
            engine.configure_workspace(alpha, str(project), "ro")
            resumed = prepare()
            assert resumed["Id"] == first["Id"]
            assert execute(resumed, "from pathlib import Path; print(Path('/home/workspace/.codex/auth-sentinel').read_text()+Path('/tmp/profile-layer').read_text())") == "alphaalpha"
            engine.configure_workspace("shared", str(project), "rw")
            restored = prepare()
            assert restored["Id"] == shared["Id"]
            assert execute(restored, "from pathlib import Path; print(Path('/home/workspace/.claude/credentials-sentinel').read_text()+Path('/tmp/profile-layer').read_text())") == "sharedshared"
            passed("switching back preserves original shared and isolated container IDs, writable layers and their own accounts")
            extra = root / "other project"
            extra.mkdir(mode=0o777)
            extra.chmod(0o777)
            plan = profiles.project_plan(engine, str(extra))
            session = engine.inspect("session")
            # A real, stopped container deliberately points to another identity.
            engine.docker.run("create", "--name", plan["name"], "--label", engine.owner + "=" + store.instance, "--label", engine.role + "=project", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--network", "container:" + session["Id"], "--volume", profiles.volumes(engine, beta)["tools-home"] + ":/home/workspace", *profiles.project_arguments(plan), image)
            try:
                with store.lock():
                    engine._project(str(extra), {"session": session["Id"], "proxy": "http://127.0.0.1:9"})
            except SPXError:
                pass
            else:
                raise AssertionError("A wrong identity volume was accepted")
            bad = engine.inspect("project", plan["name"])
            assert bad["State"]["Status"] == "created" and not bad["State"]["Running"]
            passed("a real stopped container with a foreign identity volume is rejected before its first start")
            assert engine.shutdown()["workspace_stopped"]
            assert other.docker.inspect("container", outsider["Id"])["State"]["Running"]
            assert all(not engine.docker.inspect("container", identifier)["State"]["Running"] for identifier in engine.managed())
            passed("verified shutdown stops only this instance and preserves all identity data volumes")
        finally:
            for item in (engine, other):
                try:
                    item.stop()
                except SPXError:
                    pass
                for identifier in item.managed():
                    item.owned(item.docker.inspect("container", identifier))
                    item.docker.run("rm", "-f", identifier)
            for identity in identities:
                for volume in profiles.volumes(engine, identity).values():
                    if engine.docker.inspect("volume", volume):
                        engine.docker.run("volume", "rm", volume)
            if engine.docker.inspect("image", tag):
                engine.docker.run("image", "rm", tag)
        output.write_text(json.dumps({"schema": 1, "scope": "unprivileged network-none synthetic account sentinels; no real accounts or browser", "passed": records}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="default")
    parser.add_argument("--output", type=Path, default=Path("workspace-data-results.json"))
    args = parser.parse_args()
    run(args.context, args.output)
