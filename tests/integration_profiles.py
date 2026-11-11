"""Real protected Docker/browser identity checks, using only synthetic account data."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

from enge_spx.engine import Engine, GATEWAY_IMAGE, OWNER
from enge_spx.nodes import parse_nodes
from enge_spx.resource_monitor import containers
from enge_spx.state import Store, SPXError, atomic_json
from enge_spx import workspace_profiles as profiles
from integration_runtime import execute, login_fixture, wait_lock


def sockets():
    result = set()
    for path in Path("/proc/self/fd").glob("*"):
        try:
            value = os.readlink(path)
            if value.startswith("socket:"):
                result.add(value)
        except OSError:
            pass
    return result


def run(context, runtime_report, output):
    records, measurements = [], {}
    def passed(message):
        records.append(message)
        print("PASS", message, flush=True)
    supplied = json.loads(runtime_report.read_text())
    with tempfile.TemporaryDirectory(prefix="spx-profile-runtime-") as folder:
        root = Path(folder)
        store, foreign_store = Store(root / "data"), Store(root / "foreign")
        for item in (store, foreign_store):
            item.write("settings.json", {**item.settings(), "context": context})
        store.write("images.json", supplied["images"])
        engine, foreign = Engine(store), Engine(foreign_store)
        assert engine.recipes == supplied["recipes"]
        engine.image_ids()
        node_name = engine.prefix + "-profile-fixture"
        identities = [profiles.SHARED]
        project = root / "identity project"
        project.mkdir(mode=0o777)
        project.chmod(0o777)
        secret = "synthetic-account-" + secrets.token_hex(16)
        network_report = performance_report = None
        try:
            engine.networks()
            node_dir = root / "node"
            node_dir.mkdir()
            password = secrets.token_hex(16)
            atomic_json(node_dir / "config.json", {"log": {"level": "warn"}, "dns": {"servers": [{"type": "local", "tag": "local"}]}, "inbounds": [{"type": "shadowsocks", "listen": "0.0.0.0", "listen_port": 8443, "method": "aes-128-gcm", "password": password}], "outbounds": [{"type": "direct", "tag": "direct"}], "route": {"final": "direct", "default_domain_resolver": "local"}})
            engine.docker.run("run", "-d", "--name", node_name, "--user", str(os.getuid()), "--network", engine.external, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "128m", "--label", OWNER + "-fixture=" + store.instance, "--mount", f"type=bind,source={node_dir},target=/config,readonly", GATEWAY_IMAGE, "run", "-c", "/config/config.json")
            address = engine.docker.inspect("container", node_name)["NetworkSettings"]["Networks"][engine.external]["IPAddress"]
            auth = base64.urlsafe_b64encode(("aes-128-gcm:" + password).encode()).decode().rstrip("=")
            nodes, _ = parse_nodes(f"ss://{auth}@{address}:8443#Synthetic-profile-fixture")
            engine.save_nodes(nodes)
            outsider = foreign.ensure_container("project", supplied["images"]["work"], ["--network", "none"])

            def connect():
                engine.check()
                engine.confirm()
                lock = wait_lock(store)
                try:
                    state = engine.ready()
                    worker, _ = engine._project(str(project), state)
                    engine._browser(state)
                    browser = engine.inspect("browser")
                finally:
                    lock.__exit__(None, None, None)
                return state, worker, browser

            def is_empty(worker):
                return execute(engine, worker["Id"], "from pathlib import Path; p=Path('/home/workspace'); print(not (p/'.claude/.credentials.json').exists() and not (p/'.codex/auth.json').exists())") == "True"

            def save_account(worker, identity):
                code = "import json; from pathlib import Path; p=Path('/home/workspace'); (p/'.claude').mkdir(exist_ok=True); (p/'.codex').mkdir(exist_ok=True); v=json.dumps({'fixture':" + repr(identity) + ",'synthetic':" + repr(secret) + "}); (p/'.claude/.credentials.json').write_text(v); (p/'.codex/auth.json').write_text(v); Path('/tmp/spx-profile-layer').write_text(" + repr(identity) + ")"
                execute(engine, worker["Id"], code)

            def assert_account(worker, identity):
                code = "import json; from pathlib import Path; p=Path('/home/workspace'); assert json.loads((p/'.claude/.credentials.json').read_text())['fixture']==" + repr(identity) + "; assert json.loads((p/'.codex/auth.json').read_text())['fixture']==" + repr(identity) + "; assert Path('/tmp/spx-profile-layer').read_text()==" + repr(identity) + "; print('OWN_ACCOUNT')"
                assert execute(engine, worker["Id"], code) == "OWN_ACCOUNT"

            def switch(identity, access, label):
                started = time.perf_counter()
                engine.configure_workspace(identity, str(project), access)
                measurements[label] = {"verified_stop_and_config_ms": (time.perf_counter() - started) * 1000}
                assert all(not engine.docker.inspect("container", identifier)["State"]["Running"] for identifier in engine.managed())
                assert foreign.docker.inspect("container", outsider["Id"])["State"]["Running"]

            state, shared, shared_browser = connect()
            assert is_empty(shared)
            save_account(shared, "shared")
            evidence = login_fixture(engine, shared["Id"], shared_browser["Id"], state)
            assert evidence == {"cookie": False, "storage": False}, evidence
            execute(engine, shared_browser["Id"], "from pathlib import Path; Path('/home/workspace/Downloads/spx-profile-download').write_text('shared')")
            original_shared_id = shared["Id"]
            alpha = engine.create_workspace_profile("Synthetic A")["profile"]
            identities.append(alpha)
            beta = engine.create_workspace_profile("Synthetic B")["profile"]
            identities.append(beta)
            assert engine.docker.inspect("container", shared["Id"])["State"]["Running"]
            passed("default shared identity keeps legacy paths; creating empty identities does not interrupt its real session")

            switch(alpha, "ro", "shared_to_alpha")
            state, first, first_browser = connect()
            assert is_empty(first)
            save_account(first, "alpha")
            assert execute(engine, first_browser["Id"], "from pathlib import Path; print(not Path('/home/workspace/Downloads/spx-profile-download').exists())") == "True"
            execute(engine, first_browser["Id"], "from pathlib import Path; Path('/home/workspace/Downloads/spx-profile-download').write_text('alpha')")
            evidence = login_fixture(engine, first["Id"], first_browser["Id"], state)
            assert evidence == {"cookie": False, "storage": False}, evidence
            readonly = execute(engine, first["Id"], "from pathlib import Path\ntry:\n Path.cwd().joinpath('denied').write_text('bad'); print('WRITABLE')\nexcept OSError as e:\n print(e.errno)")
            assert readonly == "30" and not (project / "denied").exists(), readonly
            passed("isolated real CLI accounts, Chromium Cookie/Storage and downloads start empty; read-only project writes are denied")

            switch(beta, "rw", "alpha_to_beta")
            state, second, second_browser = connect()
            assert is_empty(second)
            save_account(second, "beta")
            evidence = login_fixture(engine, second["Id"], second_browser["Id"], state)
            assert evidence == {"cookie": False, "storage": False}, evidence
            execute(engine, second["Id"], "from pathlib import Path; Path.cwd().joinpath('allowed').write_text('explicit-rw')")
            assert (project / "allowed").read_text() == "explicit-rw"
            passed("second isolated identity inherits no prior browser or CLI credentials and writes only after explicit read-write grant")

            switch(alpha, "ro", "beta_to_alpha")
            state, resumed, resumed_browser = connect()
            assert resumed["Id"] == first["Id"]
            assert_account(resumed, "alpha")
            restored_evidence = login_fixture(engine, resumed["Id"], resumed_browser["Id"], state)
            assert restored_evidence == {"cookie": True, "storage": True}, restored_evidence
            assert execute(engine, resumed_browser["Id"], "from pathlib import Path; print(Path('/home/workspace/Downloads/spx-profile-download').read_text())") == "alpha"
            try:
                engine.attach_command(str(project), "codex", state["session"], second["Id"], interactive=False)
            except SPXError:
                pass
            else:
                raise AssertionError("A stale terminal inherited another identity")
            passed("returning to an identity restores its real Cookie/Storage, downloads, accounts and writable layer; stale other-identity attach is rejected")

            before_sockets = sockets()
            network_report = engine.network_diagnostics()
            assert network_report["status"] == "checked", json.dumps(network_report)
            observed = network_report["objects"]["browser"]
            assert observed["status"] == "observed"
            assert observed["timezone_matches_session_offset"] is True
            assert observed["language_matches_session_primary"] is True
            assert observed["webrtc"]["offer_created"] and observed["webrtc"]["local_stun_datagrams"] == 0
            assert sockets() == before_sockets, "Diagnostics left host listening sockets open"
            assert store.read("runtime.json")["phase"] == "ready"
            rendered = json.dumps(network_report)
            for value in (secret, password, state["browser_token"], str(project), address):
                assert value not in rendered, "Sensitive context appeared in a diagnostic report"
            for name in engine.managed():
                assert not engine.docker.inspect("container", name)["HostConfig"].get("PortBindings")
            sample = containers(engine)
            running = [row for row in sample["rows"] if row["running"]]
            assert sum(row["role"] == "project" for row in running) == 1
            assert sum(row["role"] == "browser" for row in running) == 1
            measurements["active_isolated_identity"] = {"running_roles": [row["role"] for row in running], "memory_bytes_sum": sum(row.get("memory_bytes", 0) for row in running), "scope": "one synthetic idle identity plus browser/local diagnostic tabs; not real AI service load"}
            passed("real browser language/timezone/WebRTC observation is scoped, redacted, preserves guard and leaves no new host listeners or published container ports")

            performance_report = engine.network_performance()
            assert performance_report["status"] in ("checked", "partial"), json.dumps(performance_report)
            assert performance_report["verification_before"]["status"] == "verified"
            assert performance_report["verification_after"]["status"] == "verified"
            assert performance_report["budget"]["requests"] == 3
            assert store.read("runtime.json")["phase"] == "ready"
            assert sockets() == before_sockets, "Performance measurement left host sockets"
            rendered = json.dumps(performance_report)
            for value in (secret, password, state["browser_token"], str(project), address, state["proxy"], state["session"]):
                assert value not in rendered, "Sensitive context appeared in measurement evidence"
            for name in engine.managed():
                assert not engine.docker.inspect("container", name)["HostConfig"].get("PortBindings")
            measurements["network_measurement_target_status"] = {"status": performance_report["status"], "measurement": performance_report.get("measurement", {}).get("status"), "scope": "actual Engine final-chain public endpoint; service refusal/timeout may produce partial, not a successful speed measurement"}
            passed("actual Engine bounded HTTPS measurement revalidates exits, retains guard, redacts evidence and adds no host listener; target outcome is reported separately")

            switch("shared", "rw", "alpha_to_shared")
            state, restored, restored_browser = connect()
            assert restored["Id"] == original_shared_id
            assert_account(restored, "shared")
            restored_evidence = login_fixture(engine, restored["Id"], restored_browser["Id"], state)
            assert restored_evidence == {"cookie": True, "storage": True}, restored_evidence
            assert execute(engine, restored_browser["Id"], "from pathlib import Path; print(Path('/home/workspace/Downloads/spx-profile-download').read_text())") == "shared"
            passed("explicit return to compatibility mode reuses original shared accounts, browser identity, download volume and project container")

            # Remove connectivity, never grant DIRECT access to a work container.
            engine.docker.run("network", "disconnect", engine.external, engine.inspect("gateway")["Id"])
            failed = engine.network_diagnostics(browser=False)
            assert failed["status"] == "failed" and failed["stop"]["verified"]
            assert store.read("runtime.json")["phase"] == "stopped"
            assert foreign.docker.inspect("container", outsider["Id"])["State"]["Running"]
            passed("actual gateway disconnection makes diagnostics fail closed and verifies owned shutdown without affecting another instance")
            assert engine.shutdown()["background_stopped"]
            output.write_text(json.dumps({"schema": 1, "scope": "real sandboxed Chromium and protected Docker; synthetic account files/local Cookie fixture and explicit bounded public HTTPS measurement; no real AI accounts", "passed": records, "measurements": measurements, "network_report": network_report, "network_performance_report": performance_report}, indent=2) + "\n")
        finally:
            try:
                engine.shutdown()
            except (SPXError, OSError):
                pass
            for item in (engine, foreign):
                for identifier in item.managed():
                    item.owned(item.docker.inspect("container", identifier))
                    item.docker.run("rm", "-f", identifier)
            fixture = engine.docker.inspect("container", node_name)
            if fixture:
                assert fixture["Config"]["Labels"].get(OWNER + "-fixture") == store.instance
                engine.docker.run("rm", "-f", fixture["Id"])
            for identity in identities:
                for name in profiles.volumes(engine, identity).values():
                    if engine.docker.inspect("volume", name):
                        engine.docker.run("volume", "rm", name)
            if engine.docker.inspect("volume", foreign.prefix + "-tools-home"):
                engine.docker.run("volume", "rm", foreign.prefix + "-tools-home")
            for name in (engine.internal, engine.external):
                obj = engine.docker.inspect("network", name)
                if obj:
                    engine.owned(obj)
                    engine.docker.run("network", "rm", name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="default")
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("workspace-profiles-results.json"))
    args = parser.parse_args()
    run(args.context, args.runtime_report, args.output)
