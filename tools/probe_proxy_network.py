"""Explicit Docker-only P1 feasibility probe; temporary labeled resources only.

Checks core build tags and moving a stopped session to an isolated internal
bridge without replacing its project container or writable layer. Host TCP/UDP
listeners are synthetic fixtures, closed at exit; production publishes no port.
"""
import argparse
import json
from pathlib import Path
import secrets
import socket
import subprocess
import threading

CORE = "ghcr.io/sagernet/sing-box:v1.14.3"
PYTHON = "python:3.12-alpine"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prefix = "spx-p1-probe-" + secrets.token_hex(6)
    label = "io.enge.spx.p1-probe=" + prefix
    network, session, project = (prefix + suffix for suffix in ("-net", "-session", "-project"))
    report = {"schema": 1, "probe": prefix, "host_global_settings_changed": False}
    stop = threading.Event()
    tcp = socket.socket()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tcp.bind(("0.0.0.0", 0))
    udp.bind(("0.0.0.0", 0))
    tcp.listen()
    tcp.settimeout(.3)
    udp.settimeout(.3)

    def tcp_fixture():
        while not stop.is_set():
            try:
                connection, _ = tcp.accept()
                with connection:
                    connection.sendall(b"fixture")
            except socket.timeout:
                continue
            except OSError:
                return

    def udp_fixture():
        while not stop.is_set():
            try:
                data, address = udp.recvfrom(1024)
                udp.sendto(data, address)
            except socket.timeout:
                continue
            except OSError:
                return

    def docker(*arguments, check=True):
        result = subprocess.run(["docker", *map(str, arguments)], capture_output=True, text=True)
        if check and result.returncode:
            raise RuntimeError("Docker probe step failed: " + result.stderr[-3000:])
        return result.stdout.strip()

    def inspect(kind, name):
        return json.loads(docker(kind, "inspect", name))[0]

    def execute(container, code):
        return docker("exec", container, "python3", "-c", code)

    for target in (tcp_fixture, udp_fixture):
        threading.Thread(target=target, daemon=True).start()
    try:
        core = docker("run", "--rm", "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", CORE, "version")
        assert "1.14.3" in core and "with_quic" in core and "with_utls" in core, core
        report["core_version"] = core
        docker("network", "create", "--internal", "--label", label, network)
        before = inspect("network", network)
        subnet = before["IPAM"]["Config"][0]["Subnet"]
        gateway = before["IPAM"]["Config"][0]["Gateway"]
        common = ["--label", label, "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "64m"]
        docker("run", "-d", "--name", session, "--network", network, "--dns", "127.0.0.1", *common, PYTHON, "sleep", "infinity")
        first = inspect("container", session)
        session_id = first["Id"]
        session_ip = first["NetworkSettings"]["Networks"][network]["IPAddress"]
        docker("run", "-d", "--name", project, "--network", "container:" + session_id, *common, PYTHON, "sleep", "infinity")
        project_id = inspect("container", project)["Id"]
        execute(project, "from pathlib import Path; Path('/tmp/spx-p1-layer').write_text('preserved')")

        def host_paths():
            code = f'''import json,socket
result={{}}
for kind,port in ((socket.SOCK_STREAM,{tcp.getsockname()[1]}),(socket.SOCK_DGRAM,{udp.getsockname()[1]})):
 s=socket.socket(socket.AF_INET,kind);s.settimeout(.7)
 try:
  s.connect(({gateway!r},port))
  if kind==socket.SOCK_DGRAM:s.send(b'fixture')
  result['tcp' if kind==socket.SOCK_STREAM else 'udp']=s.recv(1024)==b'fixture'
 except OSError:result['tcp' if kind==socket.SOCK_STREAM else 'udp']=False
 finally:s.close()
print(json.dumps(result))'''
            return json.loads(execute(project, code))

        report["default_internal_host_access"] = host_paths()
        assert report["default_internal_host_access"] == {"tcp": True, "udp": True}
        docker("stop", project, session)
        docker("network", "disconnect", network, session)
        docker("network", "rm", network)
        docker("network", "create", "--internal", "--subnet", subnet, "--gateway", gateway, "--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated", "--label", label, network)
        docker("network", "connect", "--ip", session_ip, network, session)
        docker("start", session, project)
        report["isolated_internal_host_access"] = host_paths()
        assert report["isolated_internal_host_access"] == {"tcp": False, "udp": False}
        after = inspect("container", session)
        work = inspect("container", project)
        report["session_id_preserved"] = after["Id"] == session_id
        report["project_id_preserved"] = work["Id"] == project_id
        report["layer_preserved"] = execute(project, "from pathlib import Path; print(Path('/tmp/spx-p1-layer').read_text())") == "preserved"
        report["project_network_owner_preserved"] = work["HostConfig"]["NetworkMode"] == "container:" + session_id
        report["dns_config_preserved"] = after["HostConfig"]["Dns"] == ["127.0.0.1"]
        report["namespace_settings"] = json.loads(execute(project, "import json; from pathlib import Path; print(json.dumps({'unprivileged_port_start':Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text().strip(),'resolv_conf':Path('/etc/resolv.conf').read_text()}))"))
        assert all(report[key] for key in ("session_id_preserved", "project_id_preserved", "layer_preserved", "project_network_owner_preserved", "dns_config_preserved"))
        report["success"] = True
        print(json.dumps(report, indent=2), flush=True)
    finally:
        stop.set()
        tcp.close()
        udp.close()
        for name in (project, session):
            docker("rm", "-f", name, check=False)
        docker("network", "rm", network, check=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
