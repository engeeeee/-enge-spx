"""Bounded Linux namespace facts and explicit, credential-free blocking probes."""
from datetime import datetime, timezone
import errno
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import sys
import threading
import time
from zoneinfo import ZoneInfo


def read_text(path, limit=16384):
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as stream:
            return stream.read(limit)
    except OSError:
        return ""


def timezone_facts(localtime="/etc/localtime", zoneinfo="/usr/share/zoneinfo"):
    if hasattr(time, "tzset"):
        time.tzset()
    instant = datetime.now(timezone.utc)
    effective = instant.astimezone().utcoffset()
    result = {"name": os.environ.get("TZ", "")[:80], "offset_seconds": int(effective.total_seconds()) if effective is not None else None,
              "localtime_name": "unavailable", "localtime_offset_seconds": None, "localtime_matches_process_offset": None,
              "localtime_matches_tzif": None}
    try:
        with Path(localtime).open("rb") as source:
            data = source.read(131073)
        if len(data) > 131072:
            return result
        system = ZoneInfo.from_file(io.BytesIO(data))
        offset = instant.astimezone(system).utcoffset()
        result["localtime_offset_seconds"] = int(offset.total_seconds())
        result["localtime_matches_process_offset"] = offset == effective
        root = Path(zoneinfo).resolve()
        try:
            result["localtime_name"] = Path(localtime).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
        name = result["name"]
        # Only IANA keys; no POSIX rule or path from TZ is opened as a filename.
        if re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", name):
            expected = (root / name).resolve()
            if expected.is_relative_to(root):
                with expected.open("rb") as source:
                    result["localtime_matches_tzif"] = source.read(131073) == data
    except (OSError, ValueError, EOFError, UnicodeError):
        pass
    return result


def facts():
    ipv4, ipv6 = [], []
    for line in read_text("/proc/net/route").splitlines()[1:65]:
        try:
            fields = line.split()
            prefix = int(fields[7], 16).bit_count()
            address = lambda text: str(ipaddress.IPv4Address(int(text, 16).to_bytes(4, "little")))
            ipv4.append({"destination": address(fields[1]) + "/" + str(prefix), "gateway": address(fields[2])})
        except (ValueError, IndexError, OverflowError):
            continue
    for line in read_text("/proc/net/ipv6_route").splitlines()[:64]:
        try:
            fields = line.split()
            ipv6.append({"destination": str(ipaddress.IPv6Address(int(fields[0], 16))) + "/" + str(int(fields[1], 16)), "gateway": str(ipaddress.IPv6Address(int(fields[4], 16)))})
        except (ValueError, IndexError):
            continue
    resolvers = []
    for line in read_text("/etc/resolv.conf", 8192).splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "nameserver":
            try:
                resolvers.append(str(ipaddress.ip_address(fields[1])))
            except ValueError:
                pass
    try:
        namespace = os.readlink("/proc/self/ns/net")
    except OSError:
        namespace = "unavailable"
    return {"schema": 1, "routes": {"available": Path("/proc/net/route").is_file(), "ipv4": ipv4, "ipv6": ipv6}, "dns_servers": resolvers[:8], "network_namespace": namespace, "ipv6_interfaces": bool(read_text("/proc/net/if_inet6")), "language": {key: os.environ.get(key, "")[:80] for key in ("LANG", "LC_ALL")}, "timezone": timezone_facts()}


def failed(error):
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "no_response"
    if getattr(error, "errno", None) in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT):
        return "unsupported"
    if getattr(error, "errno", None) in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EADDRNOTAVAIL):
        return "unreachable"
    return "connection_failed"


def tcp(family, address):
    started = time.monotonic()
    value = {"test": "public_ipv4_tcp" if family == socket.AF_INET else "public_ipv6_tcp", "target": address, "port": 443}
    try:
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(1.5)
            stream.connect((address, 443))
        value["result"] = "connected"
    except OSError as error:
        value["result"] = failed(error)
    value["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return value


def dns_udp():
    started = time.monotonic()
    identifier = secrets.randbelow(65536)
    packet = struct.pack("!HHHHHH", identifier, 0x0100, 1, 0, 0, 0) + b"\x07example\x03com\x00\x00\x01\x00\x01"
    value = {"test": "public_dns_udp", "target": "1.1.1.1", "port": 53}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
            stream.settimeout(1.5)
            stream.connect(("1.1.1.1", 53))
            stream.send(packet)
            response = stream.recv(1024)
        value["result"] = "replied" if response else "no_response"
    except OSError as error:
        value["result"] = failed(error)
    value["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    return value


def resolver():
    result = {"result": "timeout"}
    def resolve():
        try:
            socket.getaddrinfo("example.com", 443, socket.AF_INET, socket.SOCK_STREAM)
            result["result"] = "answered"
        except OSError:
            result["result"] = "not_resolved"
    worker = threading.Thread(target=resolve, daemon=True)
    worker.start()
    worker.join(2)
    return dict(result)


if __name__ == "__main__":
    evidence = facts()
    if "--active" in sys.argv[1:]:
        evidence["direct_tests"] = [tcp(socket.AF_INET, "1.1.1.1"), tcp(socket.AF_INET6, "2606:4700:4700::1111"), dns_udp()]
        evidence["system_resolver"] = resolver()
    print(json.dumps(evidence))
