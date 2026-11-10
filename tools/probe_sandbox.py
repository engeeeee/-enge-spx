"""Isolated Chromium user-namespace feasibility test; no host security changes."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import time


class Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.text, self.cell = [], [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        if tag in ("td", "th"):
            self.cell, self.text = True, []

    def handle_data(self, value):
        if self.cell:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cells.append(" ".join("".join(self.text).split()))
            self.cell = False
        if tag == "tr" and self.cells:
            self.rows.append(self.cells)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"cases": [], "security_changes": ["restricted clone namespace masks", "unshare(CLONE_NEWUSER)", "chroot in the unprivileged namespace"], "host_security_settings_changed": False}
    try:
        with tempfile.TemporaryDirectory() as folder:
            dockerfile = Path(folder) / "Dockerfile"
            dockerfile.write_text("FROM debian:bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends chromium python3 ca-certificates && rm -rf /var/lib/apt/lists/*\nRUN useradd --create-home --uid 1000 workspace\nUSER 1000:1000\nCMD [\"sleep\",\"infinity\"]\n")
            subprocess.run(["docker", "build", "-t", "spx-sandbox-probe", str(folder)], check=True)
        for mode in ("default", "restricted"):
            name = "spx-sandbox-probe-" + mode
            command = ["docker", "run", "-d", "--name", name, "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only", "--network", "none", "--pids-limit", "512", "--memory", "1g", "--shm-size", "256m", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--tmpfs", "/home/workspace:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700"]
            if mode == "restricted":
                command += ["--security-opt", "seccomp=" + str(Path("src/enge_spx/resources/containers/browser-seccomp.json").resolve())]
            command += ["spx-sandbox-probe"]
            try:
                subprocess.run(command, check=True, capture_output=True)
                info = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
                sandbox = ["docker", "exec", name, "chromium", "--headless", "--disable-setuid-sandbox", "--disable-gpu", "--no-first-run", "--disable-background-networking", "--allow-chrome-scheme-url", "--user-data-dir=/tmp/spx-probe", "--dump-dom", "chrome://sandbox"]
                started = time.monotonic()
                result = subprocess.run(sandbox, capture_output=True, text=True, timeout=40)
                parsed = Table()
                parsed.feed(result.stdout)
                namespace = subprocess.run(["docker", "exec", name, "python3", "-c", "import ctypes,os,json; c=ctypes.CDLL(None,use_errno=True); r=c.unshare(0x10000000); print(json.dumps({'returncode':r,'errno':ctypes.get_errno(),'uid':os.getuid()}))"], capture_output=True, text=True)
                case = {"mode": mode, "exit": result.returncode, "elapsed_ms": round((time.monotonic() - started) * 1000), "sandbox_table": parsed.rows, "stdout": result.stdout[-16000:], "stderr": result.stderr[-10000:], "userns_probe": namespace.stdout, "privileged": info["HostConfig"]["Privileged"], "cap_add": info["HostConfig"]["CapAdd"], "cap_drop": info["HostConfig"]["CapDrop"], "read_only": info["HostConfig"]["ReadonlyRootfs"], "security_opt": ["no-new-privileges" if v.startswith("no-new-privileges") else "restricted-seccomp" for v in info["HostConfig"]["SecurityOpt"]]}
                report["cases"].append(case)
                print(json.dumps({k:v for k,v in case.items() if k not in ("stdout", "stderr")}), flush=True)
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        secure = report["cases"][-1]
        rows = {row[0].strip().lower(): row[1].strip().lower() for row in secure["sandbox_table"] if len(row) > 1}
        assert secure["exit"] == 0, secure["stderr"]
        assert rows.get("namespace sandbox") == "yes" or rows.get("layer 1 sandbox") == "namespace", rows
        assert rows.get("pid namespaces") == "yes" and rows.get("network namespaces") == "yes", rows
        assert rows.get("seccomp-bpf sandbox") == "yes", rows
        assert not secure["privileged"] and not secure["cap_add"] and "ALL" in [v.upper() for v in secure["cap_drop"]]
        report["success"] = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
