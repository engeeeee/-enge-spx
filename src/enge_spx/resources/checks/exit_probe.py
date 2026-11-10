"""Read-only exit proof executed inside the existing isolated session container."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request


def probe(proxy, detailed=False):
    # Explicit proxies must not inherit Docker's NO_PROXY bypass list.
    for name in tuple(os.environ):
        if name.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            os.environ.pop(name, None)

    def fetch(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(url, timeout=15) as response:
            return response.read(32768).decode("utf-8")

    def direct_blocked():
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=3):
                return False
        except OSError:
            return True

    with ThreadPoolExecutor(max_workers=3) as pool:
        first_job = pool.submit(fetch, "https://api.ipify.org?format=json")
        second_job = pool.submit(fetch, "https://checkip.amazonaws.com")
        direct_job = pool.submit(direct_blocked)
        first = str(ipaddress.IPv4Address(json.loads(first_job.result())["ip"]))
        second = str(ipaddress.IPv4Address(second_job.result().strip()))
        if first != second or not ipaddress.ip_address(first).is_global:
            raise ValueError("Exit IP sources disagree or the exit is not public IPv4.")
        if not direct_job.result():
            raise ValueError("Direct outbound connectivity is available.")
    evidence = {"ip": first, "direct_blocked": True, "sources": ["api.ipify.org", "checkip.amazonaws.com"]}
    if detailed:
        evidence.update(country="未知", city="未知", timezone="未知")
        try:
            geo = json.loads(fetch("https://ipwho.is/"))
            if geo.get("success") and geo.get("ip") == first:
                evidence.update(country=geo.get("country", "未知"), city=geo.get("city", "未知"), timezone=geo.get("timezone", {}).get("id", "未知"))
        except Exception:
            pass
    return evidence


def failure_code(error):
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, ssl.SSLCertVerificationError):
        return "tls_certificate_error"
    if isinstance(cause, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(cause, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(error, ValueError) and str(error) == "Direct outbound connectivity is available.":
        return "direct_path_available"
    if isinstance(error, ValueError) and str(error) == "Exit IP sources disagree or the exit is not public IPv4.":
        return "exit_sources_disagree"
    return "proxy_or_transport_failure"


if __name__ == "__main__":
    try:
        print(json.dumps(probe(sys.argv[1], "--details" in sys.argv[2:]), ensure_ascii=False))
    except Exception as error:
        raise SystemExit("Exit verification failed [SPX_PROBE:" + failure_code(error) + "]. No direct connection fallback was attempted.")
