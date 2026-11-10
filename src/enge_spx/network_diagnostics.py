"""User-triggered, evidence-scoped diagnostics; never changes the network policy."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__
from .brand import PACKAGE_RESOURCES
from .state import SPXError

ERROR_CODES = {"tls_certificate_error", "timeout", "connection_refused", "direct_path_available", "exit_sources_disagree", "proxy_or_transport_failure", "unexpected_exit"}
DIRECT_RESULTS = {"connected", "replied", "unreachable", "unsupported", "no_response", "connection_failed"}
LANGUAGE = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")


def failure_code(error):
    match = re.search(r"SPX_PROBE:([a-z_]+)", str(error))
    if match and match[1] in ERROR_CODES:
        return match[1]
    if isinstance(error, TimeoutError) or str(error) == "Docker 操作超时，请检查 Docker Desktop 状态及运行日志。":
        return "timeout"
    return "probe_failed"


def measured_probe(scope, action, results):
    started = time.perf_counter()
    row = {"scope": scope}
    try:
        result = action()
        row["result"] = "verified"
        if isinstance(result, dict) and isinstance(result.get("ip"), str):
            row["observed_ip"] = str(ipaddress.ip_address(result["ip"]))
        return result
    except Exception as error:
        row.update(result="failed", error_code=failure_code(error))
        raise
    finally:
        row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        results.append(row)


def script(name):
    return (PACKAGE_RESOURCES / "checks" / name).read_text(encoding="utf-8")


def _ip(value):
    try:
        return str(ipaddress.ip_address(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def _zone(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return "unavailable"
    try:
        ZoneInfo(value)
        return value
    except (ValueError, ZoneInfoNotFoundError):
        return "unavailable"


def _number(value, minimum, maximum):
    return value if type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value) else None


def _language(value):
    return value if isinstance(value, str) and len(value) <= 64 and LANGUAGE.fullmatch(value) else "unavailable"


def _place(value):
    return value if isinstance(value, str) and 1 <= len(value) <= 80 and all(c.isalpha() or c in " -'()." for c in value) else "unavailable"


def environment_evidence(raw):
    if not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw["schema"] != 1:
        raise ValueError("Unexpected environment schema")
    routes = {"available": False, "ipv4": [], "ipv6": []}
    supplied = raw.get("routes")
    if isinstance(supplied, dict):
        routes["available"] = supplied.get("available") is True
        for key, family in (("ipv4", 4), ("ipv6", 6)):
            for row in supplied.get(key, [])[:64] if isinstance(supplied.get(key), list) else []:
                if not isinstance(row, dict):
                    continue
                try:
                    destination = ipaddress.ip_network(row.get("destination"), strict=False)
                    gateway = ipaddress.ip_address(row.get("gateway"))
                    if destination.version == gateway.version == family:
                        routes[key].append({"destination": str(destination), "gateway": str(gateway)})
                except (ValueError, TypeError):
                    continue
    language = raw.get("language") if isinstance(raw.get("language"), dict) else {}
    languages = {key: value if isinstance(value, str) and re.fullmatch(r"(?:C|POSIX|[A-Za-z]{2,8}(?:[_-][A-Za-z0-9]{2,8})?)(?:\.[A-Za-z0-9-]{1,12})?", value) else "unavailable" for key, value in ((key, language.get(key)) for key in ("LANG", "LC_ALL"))}
    zone = raw.get("timezone") if isinstance(raw.get("timezone"), dict) else {}
    namespace = raw.get("network_namespace")
    result = {"routes": routes, "dns_servers": [value for item in raw.get("dns_servers", [])[:8] if (value := _ip(item))] if isinstance(raw.get("dns_servers"), list) else [], "network_namespace": namespace if isinstance(namespace, str) and re.fullmatch(r"net:\[[0-9]{1,20}\]", namespace) else "unavailable", "ipv6_interfaces": raw.get("ipv6_interfaces") is True, "language": languages, "timezone": {"name": _zone(zone.get("name")), "offset_seconds": _number(zone.get("offset_seconds"), -86400, 86400)}}
    checks = []
    allowed = {"public_ipv4_tcp", "public_ipv6_tcp", "public_dns_udp"}
    for row in raw.get("direct_tests", [])[:3] if isinstance(raw.get("direct_tests"), list) else []:
        if isinstance(row, dict) and row.get("test") in allowed and row.get("result") in DIRECT_RESULTS and _ip(row.get("target")):
            checks.append({"test": row["test"], "result": row["result"], "target": _ip(row["target"]), "port": 53 if row["test"] == "public_dns_udp" else 443, "elapsed_ms": _number(row.get("elapsed_ms"), 0, 60000)})
    if len(checks) == 3 and {row["test"] for row in checks} == allowed:
        result["direct_tests"] = checks
    resolver = raw.get("system_resolver")
    if isinstance(resolver, dict) and resolver.get("result") in ("answered", "not_resolved", "timeout"):
        result["system_resolver"] = {"result": resolver["result"]}
    return result


HOST_ROUTES = '''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$routes=@(Get-NetRoute -ErrorAction Stop)
$v4=@($routes | Where-Object {$_.DestinationPrefix -eq '0.0.0.0/0'} | Select-Object -First 16 DestinationPrefix,NextHop)
$v6=@($routes | Where-Object {$_.DestinationPrefix -eq '::/0'} | Select-Object -First 16 DestinationPrefix,NextHop)
$dns=@(Get-DnsClientServerAddress | ForEach-Object {$_.ServerAddresses} | Select-Object -Unique -First 8)
[pscustomobject]@{ipv4=$v4;ipv6=$v6;dns=$dns} | ConvertTo-Json -Depth 4 -Compress
'''


def host_facts():
    result = {"scope": "control_host; read-only; no public connection attempted", "system": platform.system(), "routing_available": False}
    if os.name != "nt":
        spec = importlib.util.spec_from_file_location("spx_environment_probe", PACKAGE_RESOURCES / "checks/environment_probe.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        evidence = environment_evidence(module.facts())
        return {**result, "routing_available": evidence["routes"]["available"], "source": "/proc/net/route, /proc/net/ipv6_route, /etc/resolv.conf", "evidence": evidence}
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32.dll", winmode=0x00000800)
        kernel.GetUserDefaultLocaleName.argtypes = [wintypes.LPWSTR, ctypes.c_int]
        value = ctypes.create_unicode_buffer(85)
        if kernel.GetUserDefaultLocaleName(value, len(value)):
            result["preferred_language"] = _language(value.value)
        result["language_source"] = "Windows user locale; GetUserDefaultLocaleName"
    except (OSError, AttributeError):
        result["preferred_language"] = "unavailable"
    result["timezone_offset_seconds"] = int(datetime.now().astimezone().utcoffset().total_seconds())
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        command = [str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", base64.b64encode(HOST_ROUTES.encode("utf-16-le")).decode("ascii")]
        response = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, creationflags=0x08000000)
        if response.returncode or len(response.stdout) > 32768:
            raise ValueError()
        raw = json.loads(response.stdout.lstrip("\ufeff"))
        evidence = environment_evidence({"schema": 1, "routes": {"available": True, **{key: [{"destination": item.get("DestinationPrefix"), "gateway": item.get("NextHop")} for item in raw.get(key, []) if isinstance(item, dict)] for key in ("ipv4", "ipv6")}}, "dns_servers": raw.get("dns", [])})
        result.update(routing_available=True, source="Get-NetRoute / Get-DnsClientServerAddress; NoProfile", evidence=evidence)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError):
        result["reason"] = "routing_api_unavailable"
    return result


def browser_evidence(raw):
    if not isinstance(raw, dict) or type(raw.get("schema")) is not int or raw["schema"] != 1 or raw.get("available") is not True:
        reason = raw.get("reason") if isinstance(raw, dict) else None
        return {"status": "unavailable", "reason": reason if reason in ("page_not_observed", "browser_open_failed", "browser_open_timeout") else "browser_observation_unavailable"}
    observation = raw.get("observation")
    if not isinstance(observation, dict):
        return {"status": "unavailable", "reason": "invalid_browser_observation"}
    rtc = observation.get("webrtc") if isinstance(observation.get("webrtc"), dict) else {}
    candidates = []
    for row in rtc.get("candidates", [])[:16] if isinstance(rtc.get("candidates"), list) else []:
        if not isinstance(row, dict):
            continue
        address = row.get("address")
        address = _ip(address) or (address if isinstance(address, str) and re.fullmatch(r"[a-fA-F0-9-]{16,64}\.local", address) else "unavailable")
        candidates.append({"address": address, "type": row.get("type") if row.get("type") in ("host", "srflx", "prflx", "relay") else "unknown", "protocol": row.get("protocol") if row.get("protocol") in ("udp", "tcp") else "unknown"})
    language_header = []
    for part in raw.get("accept_language", "").split(",")[:8] if isinstance(raw.get("accept_language"), str) else []:
        tag = _language(part.strip().split(";", 1)[0])
        if tag != "unavailable":
            language_header.append(tag)
    return {"status": "observed", "language": _language(observation.get("language")), "languages": [_language(value) for value in observation.get("languages", [])[:8]] if isinstance(observation.get("languages"), list) else [], "request_languages": language_header, "timezone": _zone(observation.get("timezone")), "offset_minutes": _number(observation.get("offset_minutes"), -1440, 1440), "webrtc": {"available": rtc.get("available") is True, "offer_created": rtc.get("offer_created") is True, "candidates": candidates, "local_stun_datagrams": _number(raw.get("local_stun_datagrams"), 0, 65535), "policy_file": "disable_non_proxied_udp" if raw.get("webrtc_policy_file") == "disable_non_proxied_udp" else "other_or_unavailable", "scope": "local ICE candidates and container-loopback STUN sink only; public STUN/TURN not tested"}}


def _exec_json(engine, container, name, active=False, authorization=None):
    result = engine.docker.run("exec", *(["-i"] if authorization is not None else []), container, "python3", "-c", script(name), *(["--active"] if active else []), input_data=json.dumps(authorization) if authorization is not None else None, timeout=25 if authorization is not None else 12)
    if len(result) > 128 * 1024:
        raise ValueError("Oversized diagnostic evidence")
    return json.loads(result)


def obscure(report):
    """Per-report pseudonyms preserve comparisons without a reusable address map."""
    salt = secrets.token_bytes(32)
    def alias(kind, value):
        return kind + "#" + hmac.new(salt, value.encode(), hashlib.sha256).hexdigest()[:12]
    def scrub(value, key=""):
        if isinstance(value, dict):
            return {name: scrub(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [scrub(item, key) for item in value]
        if not isinstance(value, str):
            return value
        if key in ("identity", "container"):
            return alias(key, value)
        if re.fullmatch(r"net:\[[0-9]+\]", value):
            return alias("network-namespace", value)
        try:
            address = ipaddress.ip_address(value)
            return value if address.is_loopback or address.is_unspecified else alias("IPv" + str(address.version), value)
        except ValueError:
            pass
        try:
            network = ipaddress.ip_network(value)
            return value if network.prefixlen == 0 else alias("IPv" + str(network.version) + "-network", str(network)) + "/" + str(network.prefixlen)
        except ValueError:
            pass
        return alias("mDNS", value) if re.fullmatch(r"[a-fA-F0-9-]{16,64}\.local", value) else value
    return scrub(report)


def _stop_evidence(engine):
    try:
        stopped = engine._shutdown_locked()
        return {"attempted": True, "verified": isinstance(stopped, dict) and stopped.get("workspace_stopped") is True and stopped.get("background_stopped") is True}
    except (SPXError, OSError):
        return {"attempted": True, "verified": False}


def collect(engine, browser=True):
    report = {"schema": 1, "version": __version__, "recorded_utc": datetime.now(timezone.utc).isoformat(), "status": "partial", "objects": {}, "notes": ["Host routing is read-only; active public tests run only in the controlled session.", "Probe durations include multiple HTTPS requests; they are not RTT, throughput or real AI task measurements.", "Timeout/no response is not proof that no packet left; routing policy and integration fixtures supply separate evidence.", "Language/timezone observations never change settings; geography is approximate, not a safety or anonymity proof.", "Addresses and identity/container handles are per-report aliases; paths, credentials, raw SDP and profile/account data are omitted."]}
    report["objects"]["host"] = host_facts()
    engine.log("网络检查：核对当前受控连接、路由和 DNS，不修改宿主网络或浏览器设置…")
    with engine.store.lock(timeout=45):
        initial = engine.store.read("runtime.json", {})
        if initial.get("phase") != "ready":
            report["status"] = "not_ready"
            report["objects"]["connection"] = {"status": "not_run", "reason": "workspace_requires_confirmation"}
            return obscure(report)
        timings = []
        try:
            state = engine.ready(timings=timings)
        except (SPXError, OSError) as error:
            report["status"] = "failed"
            report["objects"]["connection"] = {"status": "failed", "reason": failure_code(error), "timings": timings}
            report["stop"] = _stop_evidence(engine)
            return obscure(report)
        workspace = engine.workspace_profiles()
        report["identity"] = workspace["selected"]
        report["objects"]["first_hop"] = next((row for row in timings if row["scope"] == "first_hop"), {"status": "not_configured"})
        geography = state.get("evidence", {})
        report["objects"]["final_exit"] = {**next((row for row in timings if row["scope"] == "final_exit"), {"result": "unavailable"}), "sources": ["api.ipify.org", "checkip.amazonaws.com"], "geography": {"source": "ipwho.is; supplementary prior observation for the confirmed IP", "timezone": _zone(geography.get("timezone")), "country": _place(geography.get("country")), "city": _place(geography.get("city"))}}
        try:
            session = environment_evidence(_exec_json(engine, state["session"], "environment_probe.py", active=True))
            session.update(scope="isolated session; CLI/browser share this audited network namespace", container=state["session"])
            session["dns_path"] = {"configured_servers": ["127.0.0.1"], "source": "audit_topology verified Docker session DNS; HTTP proxy handles application target names", "limits": "loopback resolver configuration and blocking probes are not a complete packet capture or proof for all DNS destinations"}
            geo_timezone = _zone(geography.get("timezone"))
            offset = session.get("timezone", {}).get("offset_seconds")
            geographic_offset = datetime.now(timezone.utc).astimezone(ZoneInfo(geo_timezone)).utcoffset().total_seconds() if geo_timezone != "unavailable" else None
            session["timezone_vs_exit_geography"] = {"same_current_offset": offset == geographic_offset if offset is not None and geographic_offset is not None else None, "source": "approximate GeoIP timezone, current UTC offset; no settings changed"}
            report["objects"]["session"] = session
        except (SPXError, OSError, ValueError, TypeError):
            session = {}
            report["objects"]["session"] = {"status": "unavailable", "reason": "namespace_evidence_unavailable"}
        if any(row["result"] in ("connected", "replied") for row in session.get("direct_tests", [])):
            report["status"] = "unsafe"
            report["stop"] = _stop_evidence(engine)
            report["objects"]["browser"] = {"status": "not_run", "reason": "workspace_stopped_after_bypass_evidence"}
            return obscure(report)
        report["status"] = "checked" if len(session.get("direct_tests", [])) == 3 else "partial"
        report["objects"]["browser"] = {"status": "skipped" if not browser else "not_running"}
        if browser:
            obj = engine.inspect("browser")
            if obj and obj["State"]["Running"]:
                engine.log("网络检查：读取实际浏览器语言、时区和本地 WebRTC 行为，不开启调试端口…")
                from .browser_security import validate_container
                from .workspace_profiles import validate_mounts
                try:
                    validate_container(obj)
                    validate_mounts(engine, obj, workspace)
                except SPXError:
                    report["status"] = "unsafe"
                    report["stop"] = _stop_evidence(engine)
                    report["objects"]["browser"] = {"status": "rejected", "reason": "browser_identity_or_sandbox_changed"}
                    return obscure(report)
                try:
                    engine.secret_values.add(state["browser_token"])
                    observed = browser_evidence(_exec_json(engine, obj["Id"], "browser_probe.py", authorization={"token": state["browser_token"]}))
                    observed["container"] = obj["Id"]
                    report["objects"]["browser"] = observed
                    if observed["status"] != "observed":
                        report["status"] = "partial"
                    else:
                        offset = session.get("timezone", {}).get("offset_seconds")
                        browser_offset = observed.get("offset_minutes")
                        observed["timezone_matches_session_offset"] = offset == browser_offset * 60 if offset is not None and browser_offset is not None else None
                        system_language = session.get("language", {}).get("LANG", "unavailable").split("_", 1)[0].split(".", 1)[0].lower()
                        browser_language = observed["language"].split("-", 1)[0].lower()
                        observed["language_matches_session_primary"] = system_language == browser_language if system_language not in ("unavailable", "c", "posix") and browser_language != "unavailable" else None
                        rtc = observed["webrtc"]
                        rtc["local_udp_observation"] = "none_observed" if rtc["available"] and rtc["offer_created"] and rtc["local_stun_datagrams"] == 0 else "observed_or_unavailable"
                        if not rtc["available"] or not rtc["offer_created"]:
                            report["status"] = "partial"
                except (SPXError, OSError, ValueError, TypeError):
                    report["status"] = "partial"
                    report["objects"]["browser"] = {"status": "unavailable", "reason": "browser_observation_unavailable"}
            else:
                report["status"] = "partial"
        return obscure(report)
