"""Explicit, bounded HTTPS measurements inside a Linux session; no direct path."""
from contextlib import contextmanager
import http.client
import ipaddress
import json
import signal
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

TARGET_HOST = "speed.cloudflare.com"
TARGET_PORT = 443
TOTAL_SECONDS = 15
REQUESTS = (("cold_https", 1024, 4), ("cold_https", 1024, 4), ("download", 1048576, 10))


class RejectedResponse(Exception):
    pass


def proxy_address(value):
    if not isinstance(value, str) or len(value) > 128 or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError()
    parsed = urlsplit(value)
    address = ipaddress.IPv4Address(parsed.hostname)
    if parsed.scheme != "http" or parsed.port != 2080 or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment or address.is_unspecified or address.is_multicast:
        raise ValueError()
    return str(address), parsed.port


@contextmanager
def hard_timeout(seconds):
    # This runs in its own Linux `docker exec python3` main process, never in
    # the host GUI/guard. Socket timeouts alone cannot stop drip-fed headers.
    if not hasattr(signal, "setitimer") or seconds <= 0:
        raise TimeoutError()
    def expired(signum, frame):
        raise TimeoutError()
    started = time.monotonic()
    previous = signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, max(.001, timer[0] - (time.monotonic() - started)), timer[1])


def error_code(error):
    if isinstance(error, ssl.SSLCertVerificationError):
        return "tls_certificate_error"
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(error, RejectedResponse):
        return "response_rejected"
    return "proxy_or_transport_failure"


def request(proxy, kind, size, seconds):
    started = time.monotonic()
    row = {"kind": kind, "requested_bytes": size, "result": "failed", "bytes_received": 0}
    connection = response = None
    try:
        host, port = proxy_address(proxy)
        with hard_timeout(seconds):
            context = ssl.create_default_context()
            context.set_alpn_protocols(["http/1.1"])
            connection = http.client.HTTPSConnection(host, port, timeout=min(3, seconds), context=context)
            connection.set_tunnel(TARGET_HOST, TARGET_PORT)
            connection.connect()
            row["tunnel_tls_ms"] = round((time.monotonic() - started) * 1000, 3)
            connection.request("GET", "/__down?bytes=" + str(size), headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache", "Connection": "close", "User-Agent": "ENGE-SPX-network-check/1"})
            response = connection.getresponse()
            row["http_status"] = response.status
            length = response.getheader("Content-Length")
            if response.status != 200 or response.getheader("Content-Encoding", "identity").lower() != "identity" or (length is not None and length != str(size)):
                raise RejectedResponse()
            first = response.read(1)
            if not first:
                raise RejectedResponse()
            first_at = time.monotonic()
            row.update(first_byte_ms=round((first_at - started) * 1000, 3), bytes_received=1)
            while row["bytes_received"] <= size:
                # Only retain one small buffer. One extra byte detects an
                # oversized response without accepting unbounded chunked data.
                data = response.read(min(16384, size + 1 - row["bytes_received"]))
                if not data:
                    break
                row["bytes_received"] += len(data)
            if row["bytes_received"] != size:
                raise RejectedResponse()
            finished = time.monotonic()
            row.update(result="measured", body_ms=round((finished - first_at) * 1000, 3))
            if kind == "download":
                elapsed = finished - started
                row["request_bytes_per_second"] = size / elapsed if elapsed > .001 else None
                body_elapsed = finished - first_at
                row["body_bytes_per_second"] = (size - 1) / body_elapsed if body_elapsed > .001 else None
    except Exception as error:
        row.update(result="failed", error_code=error_code(error))
    finally:
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()
    row["total_ms"] = round((time.monotonic() - started) * 1000, 3)
    return row


def measure(proxy):
    proxy_address(proxy)
    started = time.monotonic()
    rows = []
    for kind, size, seconds in REQUESTS:
        remaining = TOTAL_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            rows.append({"kind": kind, "requested_bytes": size, "bytes_received": 0, "result": "not_run", "error_code": "time_budget"})
        else:
            rows.append(request(proxy, kind, size, min(seconds, remaining)))
    return {"schema": 1, "samples": rows, "elapsed_ms": round((time.monotonic() - started) * 1000, 3)}


if __name__ == "__main__":
    try:
        raw = sys.stdin.read(4097)
        supplied = json.loads(raw) if len(raw) <= 4096 else None
        if not isinstance(supplied, dict) or set(supplied) != {"proxy"}:
            raise ValueError()
        print(json.dumps(measure(supplied["proxy"]), allow_nan=False))
    except Exception:
        raise SystemExit("SPX_NETWORK_MEASUREMENT:unavailable") from None
