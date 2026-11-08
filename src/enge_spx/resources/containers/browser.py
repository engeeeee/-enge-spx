import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.parse


def allowed_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        return bool(parsed.hostname) and not parsed.username and not parsed.password and (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")))
    except ValueError:
        return False


def browser_profile(home):
    profile = Path(home) / ".config/chromium-spx"
    # Existing profiles belong to the same user and volume; move only once while
    # the old browser is stopped, retaining cookies and bookmarks.
    previous = profile.with_name("chromium-ewb")
    if not profile.exists() and previous.is_dir():
        previous.rename(profile)
    return str(profile)


def main():
    token = os.environ.get("SPX_BROWSER_TOKEN", "")
    proxy = os.environ.get("HTTP_PROXY", "")
    if not re.fullmatch("[a-f0-9]{64}", token) or not proxy.startswith("http://"):
        raise SystemExit("Missing browser authorization or proxy configuration.")
    os.environ["DISPLAY"] = ":99"
    profile = browser_profile(Path.home())
    chromium = ["chromium", "--no-sandbox", "--no-first-run", "--disable-dev-shm-usage", "--disable-quic", "--disable-background-networking", "--password-store=basic", "--user-data-dir=" + profile, "--proxy-server=" + proxy]
    children = []
    def spawn(args):
        child = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        children.append(child)
        return child
    stopped = threading.Event()
    def stop(signum=None, frame=None):
        stopped.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    vnc = spawn(["Xvnc", ":99", "-geometry", "1440x900", "-depth", "24", "-rfbport", "5900", "-localhost", "yes", "-SecurityTypes", "None", "-AlwaysShared", "-AcceptCutText", "1", "-SendCutText", "1"])
    for _ in range(100):
        if Path("/tmp/.X11-unix/X99").exists():
            break
        if vnc.poll() is not None:
            raise SystemExit("VNC display failed to start.")
        time.sleep(0.1)
    spawn(["openbox"])
    browser = spawn([*chromium, "about:blank"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            candidate = self.headers.get("X-SPX-Token", "")
            # A preserved 0.2 work image may still issue its original header.
            if not candidate and os.environ.get("EWB_BROWSER_TOKEN"):
                candidate = self.headers.get("X-EWB-Token", "")
            if self.path != "/open" or not hmac.compare_digest(candidate, token):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 10000:
                    raise ValueError()
                value = json.loads(self.rfile.read(size))["url"]
                if not allowed_url(value):
                    raise ValueError()
                # No shell and no command-line options supplied by the URL.
                child = subprocess.Popen([*chromium, "--new-tab", value], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.terminate()
                self.send_response(204)
                self.end_headers()
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
    server = ThreadingHTTPServer(("127.0.0.1", 6081), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while not stopped.wait(1):
            if any(p.poll() is not None for p in (vnc, browser)):
                break
    finally:
        server.shutdown()
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
