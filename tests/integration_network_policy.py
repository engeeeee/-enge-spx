"""Real Docker bridge migration, rollback, DNS/UDP/IPv6 and host-path evidence."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from unittest.mock import patch

from enge_spx.engine import Engine
from enge_spx.network_policy import JOURNAL, MODE, _replace, validate
from enge_spx.state import SPXError, Store

PYTHON = "python:3.12-alpine"
DNS = '''import socket,struct
from pathlib import Path
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('0.0.0.0',53))
while True:
 data,address=s.recvfrom(4096)
 if len(data)<12:continue
 with Path('/tmp/queries').open('ab') as log:log.write(data[12:]+b'\\n')
 answer=data[:2]+bytes.fromhex('81800001000100000000')+data[12:]+bytes.fromhex('c00c00010001000000010004cb007107')
 s.sendto(answer,address)
'''


def execute(engine, container, code):
    return engine.docker.run("exec", container, "python3", "-c", code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="default")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records, report = [], {"schema": 1, "host_global_settings_changed": False}
    def passed(message):
        records.append(message)
        print("PASS", message, flush=True)
    report["passed"] = records
    with tempfile.TemporaryDirectory(prefix="spx-network-policy-") as temporary:
        base = Path(temporary)
        store = Store(base / "private")
        store.write("settings.json", {**store.settings(), "context": args.context})
        engine = Engine(store)
        store.write("images.json", {"work": PYTHON})
        dns_name, foreign_name = engine.prefix + "-dns-fixture", engine.prefix + "-foreign-fixture"
        tcp, udp = socket.socket(), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp.bind(("0.0.0.0", 0)); tcp.listen(); tcp.settimeout(.2)
        udp.bind(("0.0.0.0", 0)); udp.settimeout(.2)
        stopped, hits = threading.Event(), []
        def serve(stream):
            while not stopped.is_set():
                try:
                    if stream:
                        connection, _ = tcp.accept()
                        with connection:
                            connection.sendall(b"fixture")
                        hits.append("tcp")
                    else:
                        data, peer = udp.recvfrom(4096)
                        udp.sendto(data, peer)
                        hits.append("udp")
                except socket.timeout:
                    continue
                except OSError:
                    return
        for kind in (True, False):
            threading.Thread(target=serve, args=(kind,), daemon=True).start()
        try:
            engine.docker.run("pull", PYTHON, timeout=300)
            image = engine.docker.inspect("image", PYTHON)["Id"]
            engine.docker.run("network", "create", "--internal", "--label", engine.owner + "=" + store.instance, engine.internal)
            engine.docker.run("network", "create", "--label", engine.owner + "=" + store.instance, engine.external)
            old = engine.docker.inspect("network", engine.internal)
            subnet = ipaddress.ip_network(old["IPAM"]["Config"][0]["Subnet"])
            bridge_ip = old["IPAM"]["Config"][0]["Gateway"]
            session = engine.ensure_container("session", image, ["--user", "1000:1000", "--network", engine.internal, "--ip", str(subnet[3]), "--dns", "127.0.0.1", "--read-only", "--memory", "64m"], ["sleep", "infinity"])
            gateway = engine.ensure_container("gateway", image, ["--user", "1000:1000", "--network", engine.internal, "--ip", str(subnet[2]), "--memory", "64m"], ["sleep", "infinity"])
            engine.docker.run("network", "connect", "--gw-priority", "1", engine.external, gateway["Id"])
            project = engine.ensure_container("project", image, ["--user", "1000:1000", "--network", "container:" + session["Id"], "--memory", "64m"], ["sleep", "infinity"], name=engine.prefix + "-project-fixture")
            execute(engine, project["Id"], "from pathlib import Path; Path('/tmp/p1-layer').write_text('preserved')")
            def host_access():
                code = f'''import socket,json
result={{}}
for kind,port in ((socket.SOCK_STREAM,{tcp.getsockname()[1]}),(socket.SOCK_DGRAM,{udp.getsockname()[1]})):
 s=socket.socket(socket.AF_INET,kind);s.settimeout(.5)
 try:
  s.connect(({bridge_ip!r},port))
  if kind==socket.SOCK_DGRAM:s.send(b'fixture')
  result['tcp' if kind==socket.SOCK_STREAM else 'udp']=s.recv(100)==b'fixture'
 except OSError:result['tcp' if kind==socket.SOCK_STREAM else 'udp']=False
 finally:s.close()
print(json.dumps(result))'''
                return json.loads(execute(engine, project["Id"], code))
            assert host_access() == {"tcp": True, "udp": True}, "Baseline host fixtures must be reachable"
            engine.networks()
            assert all(not engine.docker.inspect("container", obj["Id"])["State"]["Running"] for obj in (gateway, session, project))
            assert store.read(JOURNAL)["phase"] == "complete"
            validate(engine, engine.docker.inspect("network", engine.internal), True)
            engine.docker.run("start", session["Id"], project["Id"], gateway["Id"])
            assert execute(engine, project["Id"], "from pathlib import Path; print(Path('/tmp/p1-layer').read_text())") == "preserved"
            assert engine.inspect("session")["Id"] == session["Id"]
            assert engine.docker.inspect("container", project["Id"])["HostConfig"]["NetworkMode"] == "container:" + session["Id"]
            assert host_access() == {"tcp": False, "udp": False}
            passed("actual Engine upgrades live owned resources while stopped; session/project IDs and writable layer survive; host TCP/UDP blocked")

            engine.docker.run("run", "-d", "--name", dns_name, "--network", engine.external, "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--label", engine.owner + "-fixture=" + store.instance, image, "python3", "-u", "-c", DNS)
            dns_ip = engine.docker.inspect("container", dns_name)["NetworkSettings"]["Networks"][engine.external]["IPAddress"]
            query = "123401000001000000000000" + "0373707807696e76616c69640000010001"
            def dns_query(container, server):
                return execute(engine, container, f'''import socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(.7)
try:
 s.sendto(bytes.fromhex({query!r}),({server!r},53));data=s.recv(4096);print(data.hex())
except OSError:print('BLOCKED')
''')
            positive = "BLOCKED"
            for _ in range(10):
                positive = dns_query(gateway["Id"], dns_ip)
                if positive != "BLOCKED":
                    break
                if not engine.docker.inspect("container", dns_name)["State"]["Running"]:
                    raise AssertionError("DNS fixture exited: " + engine.docker.run("logs", dns_name))
                time.sleep(.1)
            assert positive.startswith("12348180") and positive.endswith("cb007107"), positive + "; DNS fixture: " + engine.docker.run("logs", dns_name) + "; gateway routes: " + execute(engine, gateway["Id"], "from pathlib import Path; print(Path('/proc/net/route').read_text())")
            count = execute(engine, dns_name, "from pathlib import Path; print(Path('/tmp/queries').stat().st_size)")
            assert dns_query(project["Id"], dns_ip) == "BLOCKED"
            # Adversarially configured DNS still must not make Docker forward
            # external requests from an internal-only namespace.
            probe = engine.ensure_container("dns-probe", image, ["--user", "1000:1000", "--network", engine.internal, "--dns", dns_ip, "--read-only", "--memory", "64m"], ["sleep", "infinity"])
            embedded = dns_query(probe["Id"], "127.0.0.11")
            assert embedded == "BLOCKED" or embedded[6:8] == "02", embedded
            assert execute(engine, dns_name, "from pathlib import Path; print(Path('/tmp/queries').stat().st_size)") == count
            ipv6 = execute(engine, project["Id"], "import socket\ns=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);s.settimeout(.5)\ntry:s.connect(('2606:4700:4700::1111',443));print('LEAK')\nexcept OSError:print('BLOCKED')")
            assert ipv6 == "BLOCKED", ipv6
            passed("worker raw UDP/DNS and IPv6 cannot bypass; internal Docker DNS does not forward to the healthy external DNS fixture")
            engine.docker.run("stop", probe["Id"])
            engine.docker.run("rm", probe["Id"])
            engine.stop()
            original, endpoints = store.read(JOURNAL)["original"], store.read(JOURNAL)["endpoints"]
            _replace(engine, original, endpoints, False)
            (store.home / JOURNAL).unlink()
            run = engine.docker.run
            injected = False
            def fail_once(*arguments, **kwargs):
                nonlocal injected
                if not injected and arguments[:2] == ("network", "connect"):
                    injected = True
                    raise SPXError("Synthetic reconnect permission failure")
                return run(*arguments, **kwargs)
            with patch.object(engine.docker, "run", side_effect=fail_once):
                try:
                    engine.networks()
                except SPXError:
                    pass
                else:
                    raise AssertionError("Reconnect failure was ignored")
            assert store.read(JOURNAL)["phase"] == "rolled-back"
            assert not engine.docker.inspect("network", engine.internal).get("Options", {}).get(MODE) == "isolated"
            assert all(not engine.docker.inspect("container", obj["Id"])["State"]["Running"] for obj in (gateway, session, project))
            engine.docker.run("cp", project["Id"] + ":/tmp/p1-layer", str(base / "preserved"))
            assert (base / "preserved").read_text() == "preserved"
            engine.networks()
            passed("reconnect failure rolls back metadata only, never starts the old policy; retry succeeds without losing layers")
            _replace(engine, original, endpoints, False)
            (store.home / JOURNAL).unlink()
            class Interrupted(BaseException):
                pass
            def interrupt(*arguments, **kwargs):
                if arguments[:2] == ("network", "connect"):
                    raise Interrupted()
                return run(*arguments, **kwargs)
            with patch.object(engine.docker, "run", side_effect=interrupt):
                try:
                    engine.networks()
                except Interrupted:
                    pass
            assert store.read(JOURNAL)["phase"] == "upgrading"
            Engine(store).networks()
            assert store.read(JOURNAL)["phase"] == "complete"
            passed("interrupted migration resumes missing endpoint connections using a versioned journal; container IDs retained")
            _replace(engine, original, endpoints, False)
            (store.home / JOURNAL).unlink()
            engine.docker.run("run", "-d", "--name", foreign_name, "--network", engine.internal, "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--label", engine.owner + "-fixture=" + store.instance, image, "sleep", "infinity")
            with patch.object(engine.docker, "run", wraps=run) as calls:
                try:
                    engine.networks()
                except SPXError:
                    pass
                else:
                    raise AssertionError("Foreign resource was not rejected")
                assert not any(call.args[:2] in (("network", "rm"), ("network", "disconnect")) for call in calls.call_args_list)
            assert engine.docker.inspect("container", foreign_name)["State"]["Running"]
            passed("foreign endpoint prevents migration before any detach/delete; unrelated container left running")
            report.update(success=True, docker=engine.doctor())
        finally:
            stopped.set(); tcp.close(); udp.close()
            for name in (foreign_name, dns_name):
                obj = engine.docker.inspect("container", name)
                if obj:
                    assert obj["Config"]["Labels"].get(engine.owner + "-fixture") == store.instance
                    engine.docker.run("rm", "-f", obj["Id"])
            try:
                engine.stop()
            finally:
                for name in engine.managed():
                    engine.owned(engine.docker.inspect("container", name))
                    engine.docker.run("rm", "-f", name)
                for name in (engine.internal, engine.external):
                    obj = engine.docker.inspect("network", name)
                    if obj:
                        engine.owned(obj)
                        engine.docker.run("network", "rm", name)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
