"""Opt-in final-chain measurements, kept separate from safety verification."""
from datetime import datetime, timezone
import ipaddress
import json
import math
import statistics

from . import __version__
from .network_diagnostics import failure_code, obscure, script, _stop_evidence
from .state import SPXError

PAYLOAD_BYTES = 1048576 + 2048
KINDS = (("cold_https", 1024), ("cold_https", 1024), ("download", 1048576))
RESULTS = {"measured", "failed", "not_run"}
ERRORS = {"tls_certificate_error", "timeout", "connection_refused", "response_rejected", "proxy_or_transport_failure", "time_budget"}


def number(value, maximum=1000000000000):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum else None


def evidence(raw):
    if not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw["schema"] != 1 or not isinstance(raw.get("samples"), list) or len(raw["samples"]) != 3:
        raise ValueError()
    rows = []
    for supplied, (kind, size) in zip(raw["samples"], KINDS):
        if not isinstance(supplied, dict) or supplied.get("kind") != kind or supplied.get("requested_bytes") != size or supplied.get("result") not in RESULTS:
            raise ValueError()
        received = supplied.get("bytes_received")
        if type(received) is not int or not 0 <= received <= size + 1:
            raise ValueError()
        row = {"kind": kind, "requested_bytes": size, "bytes_received": received, "result": supplied["result"]}
        for key in ("tunnel_tls_ms", "first_byte_ms", "total_ms", "body_ms"):
            row[key] = number(supplied.get(key), 30000)
        status = supplied.get("http_status")
        row["http_status"] = status if type(status) is int and 100 <= status <= 599 else None
        if row["result"] == "measured":
            if received != size or row["http_status"] != 200 or row["first_byte_ms"] is None or row["total_ms"] is None or row["tunnel_tls_ms"] is None or not row["tunnel_tls_ms"] <= row["first_byte_ms"] <= row["total_ms"]:
                raise ValueError()
            if kind == "download":
                # Compute rates from allowlisted byte/time counters rather
                # than trusting an arbitrary rate string/number from the guest.
                total = row["total_ms"]
                body = row["body_ms"]
                row["request_bytes_per_second"] = size * 1000 / total if total > 1 else None
                row["body_bytes_per_second"] = (size - 1) * 1000 / body if body is not None and 1 < body <= total else None
        else:
            row["error_code"] = supplied.get("error_code") if supplied.get("error_code") in ERRORS else "measurement_unavailable"
        rows.append(row)
    first_bytes = [row["first_byte_ms"] for row in rows if row["kind"] == "cold_https" and row["result"] == "measured"]
    download = rows[2]
    rate = download.get("request_bytes_per_second")
    body_rate = download.get("body_bytes_per_second")
    return {"status": "measured" if all(row["result"] == "measured" for row in rows) else "partial", "elapsed_ms": number(raw.get("elapsed_ms"), 30000), "samples": rows,
            "cold_https_first_byte_ms": {"count": len(first_bytes), **({"min": min(first_bytes), "median": statistics.median(first_bytes), "max_sampled": max(first_bytes)} if first_bytes else {})},
            "download": {"result": download["result"], "bytes_received": download["bytes_received"], "request_mbps": rate * 8 / 1000000 if rate is not None else None, "body_mbps": body_rate * 8 / 1000000 if body_rate is not None else None}}


def stamp(state):
    return tuple(state.get(key) for key in ("gateway", "session", "policy", "confirmed")) if isinstance(state, dict) and state.get("phase") == "ready" else None


def gateway_proxy(engine, state):
    obj = engine.inspect("gateway")
    if not obj or obj.get("Id") != state["gateway"] or obj.get("State", {}).get("Running") is not True:
        raise SPXError("测量网关已经变化，请重新确认工作区。")
    try:
        address = ipaddress.IPv4Address(obj["NetworkSettings"]["Networks"][engine.internal]["IPAddress"])
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError()
        expected = "http://" + str(address) + ":2080"
        if state.get("proxy") != expected:
            raise ValueError()
        return expected
    except (ValueError, KeyError, TypeError):
        raise SPXError("测量入口与已核验的内部网关不一致，已拒绝请求。") from None


def collect(engine):
    report = {"schema": 1, "kind": "network_performance", "version": __version__, "recorded_utc": datetime.now(timezone.utc).isoformat(), "status": "not_ready",
              "target": {"service": "Cloudflare", "host": "speed.cloudflare.com", "path": "/__down", "https": True},
              "budget": {"requests": 3, "requested_payload_bytes": PAYLOAD_BYTES, "maximum_read_payload_bytes": PAYLOAD_BYTES + 3, "measurement_seconds": 15},
              "notes": ["Explicit final-chain HTTP measurements only; no host public probe or first-hop download path.",
                        "Cold HTTPS first-byte time includes proxy CONNECT, TLS and origin work; it is not RTT. Existing exit verification times contain multiple requests.",
                        "Download rates describe one small HTTPS response, not a line maximum, AI request latency or noVNC experience; do not subtract hop timings to infer a bottleneck.",
                        "The payload budget excludes HTTP/TLS/TCP and safety-verification traffic. The target can observe the final public exit and requests; no result telemetry is uploaded.",
                        "Guard remains active while measurement releases the operation lock. Changed sessions discard results instead of stopping a replacement workspace."]}
    with engine.store.lock("network-measurement"):
        with engine.store.lock(timeout=45):
            initial = engine.store.read("runtime.json", {})
            if stamp(initial) is None:
                return report
            timings = []
            try:
                state = engine.ready(timings=timings)
                proxy = gateway_proxy(engine, state)
                expected = stamp(state)
                report["container"] = state["session"]
                report["verification_before"] = {"status": "verified", "timings": timings}
            except (SPXError, OSError, ValueError, KeyError, TypeError) as error:
                report.update(status="failed", verification_before={"status": "failed", "reason": failure_code(error), "timings": timings}, stop=_stop_evidence(engine))
                return obscure(report)
        # Do not hold the guard's operation lock over a potentially slow HTTPS
        # transfer. The existing session/gateway remain the only traffic path.
        engine.log("网络测量：通过当前最终链路发起 3 次有界 HTTPS 请求，约 1 MiB 载荷…")
        try:
            output = engine.docker.run("exec", "-i", state["session"], "python3", "-c", script("network_probe.py"), input_data=json.dumps({"proxy": proxy}), timeout=22)
            if len(output) > 32768:
                raise ValueError()
            measurement = evidence(json.loads(output))
        except (SPXError, OSError, ValueError, TypeError, KeyError):
            measurement = {"status": "unavailable", "reason": "measurement_unavailable"}
        with engine.store.lock(timeout=45):
            current = engine.store.read("runtime.json", {})
            if stamp(current) != expected:
                report.update(status="stale", measurement={"status": "discarded", "reason": "workspace_changed"}, verification_after={"status": "not_run", "reason": "workspace_changed"})
                return obscure(report)
            timings = []
            try:
                engine.log("网络测量：再次核对两级出口和拓扑…")
                engine.ready(timings=timings)
            except (SPXError, OSError, ValueError, KeyError, TypeError) as error:
                report.update(status="failed", measurement={"status": "discarded", "reason": "verification_failed"}, verification_after={"status": "failed", "reason": failure_code(error), "timings": timings}, stop=_stop_evidence(engine))
                return obscure(report)
            if any(row.get("error_code") == "tls_certificate_error" for row in measurement.get("samples", [])):
                report.update(status="failed", measurement={"status": "discarded", "reason": "tls_certificate_error"}, verification_after={"status": "verified", "timings": timings}, stop=_stop_evidence(engine))
                return obscure(report)
            report.update(status="checked" if measurement["status"] == "measured" else "partial", measurement=measurement, verification_after={"status": "verified", "timings": timings})
        return obscure(report)
