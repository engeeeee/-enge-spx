"""Chromium's own sandbox report plus evidence from its actual renderer."""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


class SandboxTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.text, self.in_cell = [], [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        if tag in ("td", "th"):
            self.in_cell, self.text = True, []

    def handle_data(self, value):
        if self.in_cell:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.cells.append(" ".join("".join(self.text).split()))
            self.in_cell = False
        if tag == "tr" and len(self.cells) >= 2:
            self.rows.append(self.cells)


def parse_status(html):
    parsed = SandboxTable()
    parsed.feed(html)
    values = {row[0].strip().lower(): row[1].strip().lower() for row in parsed.rows}
    result = {"namespace": values.get("namespace sandbox") == "yes" or values.get("layer 1 sandbox") == "namespace", "pid_namespace": values.get("pid namespaces") == "yes", "network_namespace": values.get("network namespaces") == "yes", "seccomp_bpf": values.get("seccomp-bpf sandbox") == "yes"}
    if not all(result.values()):
        raise RuntimeError("CHROMIUM_SANDBOX_UNAVAILABLE: namespace, PID, network or seccomp verification failed")
    return result


def verify_chromium(arguments):
    if os.getuid() == 0 or any(value in arguments for value in ("--no-sandbox", "--disable-namespace-sandbox", "--disable-seccomp-filter-sandbox")):
        raise RuntimeError("CHROMIUM_SANDBOX_UNAVAILABLE: unsafe user or arguments")
    with tempfile.TemporaryDirectory(prefix="spx-sandbox-", dir="/tmp") as profile:
        command = [value for value in arguments if not value.startswith("--user-data-dir=")]
        command += ["--user-data-dir=" + profile, "--headless", "--disable-gpu", "--allow-chrome-scheme-url", "--dump-dom", "chrome://sandbox"]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        if result.returncode or len(result.stdout) > 1024 * 1024:
            raise RuntimeError("CHROMIUM_SANDBOX_UNAVAILABLE: the kernel, seccomp or LSM blocked initialization")
        return parse_status(result.stdout.decode("utf-8", errors="replace"))


def read_status(pid):
    return {key: value.strip() for key, value in (line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line)}


def verify_renderer(browser_pid, timeout=12):
    base = read_status(browser_pid)
    base_filters = int(base.get("Seccomp_filters", "0"))
    base_depth = len(base.get("NSpid", "").split())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = {}
        for path in Path("/proc").iterdir():
            if path.name.isdecimal():
                try:
                    records[int(path.name)] = read_status(int(path.name))
                except (OSError, ValueError):
                    pass
        for pid, status in records.items():
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if b"--type=renderer" not in command:
                continue
            ancestor, visited = pid, set()
            while ancestor in records and ancestor not in visited and ancestor != browser_pid:
                visited.add(ancestor)
                ancestor = int(records[ancestor].get("PPid", "0"))
            if ancestor != browser_pid:
                continue
            good = {"non_root": int(status["Uid"].split()[0]) != 0, "no_new_privileges": status.get("NoNewPrivs") == "1", "no_capabilities": int(status.get("CapEff", "1"), 16) == 0, "seccomp": status.get("Seccomp") == "2", "additional_seccomp_filter": int(status.get("Seccomp_filters", "0")) > base_filters > 0, "nested_pid_namespace": len(status.get("NSpid", "").split()) > base_depth > 0}
            if all(good.values()):
                return good
        time.sleep(.1)
    raise RuntimeError("CHROMIUM_SANDBOX_UNAVAILABLE: renderer kernel evidence missing")
