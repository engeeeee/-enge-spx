import ipaddress
import json
import socket
import sys
import urllib.request


def probe(proxy):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    def fetch(url):
        with opener.open(url, timeout=15) as response:
            return response.read(32768).decode("utf-8")
    first = str(ipaddress.IPv4Address(json.loads(fetch("https://api.ipify.org?format=json"))["ip"]))
    second = str(ipaddress.IPv4Address(fetch("https://checkip.amazonaws.com").strip()))
    if first != second or not ipaddress.ip_address(first).is_global:
        raise ValueError("Exit IP sources disagree or the exit is not public IPv4.")
    direct_blocked = False
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=3):
            pass
    except OSError:
        direct_blocked = True
    if not direct_blocked:
        raise ValueError("Direct outbound connectivity is available; refusing this network.")
    evidence = {"ip": first, "direct_blocked": True, "country": "未知", "city": "未知", "timezone": "未知", "sources": ["api.ipify.org", "checkip.amazonaws.com"]}
    try:
        geo = json.loads(fetch("https://ipwho.is/"))
        if geo.get("success") and geo.get("ip") == first:
            evidence.update({"country": geo.get("country", "未知"), "city": geo.get("city", "未知"), "timezone": geo.get("timezone", {}).get("id", "未知")})
    except Exception:
        pass  # Geography is approximate supplementary information, not exit proof.
    return evidence


if __name__ == "__main__":
    try:
        print(json.dumps(probe(sys.argv[1]), ensure_ascii=False))
    except Exception:
        raise SystemExit("Exit verification failed. No direct connection fallback was attempted.")
