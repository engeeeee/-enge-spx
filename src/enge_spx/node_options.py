"""Bounded protocol parameters. Errors identify fields, never input values."""
import base64
import ipaddress
import re
import ssl

FINGERPRINTS = frozenset({"chrome", "firefox", "edge", "safari", "ios", "android", "360", "qq", "random", "randomized"})


class NodeParameterError(ValueError):
    """A trusted field/reason pair; neither is copied from a node's value."""


def invalid(field, reason):
    raise NodeParameterError("参数 " + field + "：" + reason)


def boolean(value, field):
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int)) and str(value).lower() in ("0", "1", "true", "false", "yes", "no"):
        return str(value).lower() in ("1", "true", "yes")
    invalid(field, "必须为明确的布尔值")


def text(value, field, limit=2048, empty=True):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or not empty and not value:
        invalid(field, "必须为长度受限、无控制字符的文本")
    return value


def host(value, field):
    value = text(value, field, 253, False)
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.?", value) or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in value.rstrip(".").split(".")):
        invalid(field, "域名或 IP 地址无效")
    return value


def integer(value, field, low, high):
    if isinstance(value, bool):
        invalid(field, "整数范围无效")
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError):
        invalid(field, "必须为整数")
    if str(result) != str(value) and not isinstance(value, int):
        invalid(field, "必须为整数")
    if not low <= result <= high:
        invalid(field, "整数范围无效")
    return result


def tls_options(raw, kind, server):
    tls = raw.get("tls", {"enabled": True} if str(raw.get("type", "")).lower() == "https" else {})
    if isinstance(tls, bool):
        tls = {"enabled": tls}
    if not isinstance(tls, dict):
        invalid("tls", "必须为对象")
    if boolean(tls.get("insecure", False), "tls.insecure"):
        invalid("tls.insecure", "必须验证 TLS 证书，禁止跳过校验")
    known = {"enabled", "server_name", "insecure", "alpn", "reality", "utls", "certificate", "min_version", "max_version"}
    if set(tls) - known:
        invalid("tls", "包含不支持的选项；不读取宿主证书路径或启用额外权限")
    required = kind in ("trojan", "vless", "hysteria2") or str(raw.get("type", "")).lower() == "https"
    enabled = boolean(tls.get("enabled", required), "tls.enabled")
    if required and not enabled:
        invalid("tls.enabled", "此协议必须启用 TLS")
    if enabled and kind in ("socks", "shadowsocks"):
        invalid("tls.enabled", "此协议不支持额外 TLS 包装")
    if not enabled:
        if any(tls.get(key) for key in ("reality", "utls", "certificate", "alpn")):
            invalid("tls.enabled", "TLS 参数不能在禁用 TLS 时生效")
        return None
    result = {"enabled": True, "server_name": host(tls.get("server_name") or server, "tls.server_name")}
    if tls.get("alpn"):
        values = tls["alpn"]
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            invalid("tls.alpn", "必须为受限字符串列表")
        result["alpn"] = [text(value, "tls.alpn", 64, False) for value in values]
        if kind == "hysteria2" and result["alpn"] != ["h3"]:
            invalid("tls.alpn", "Hysteria2 使用 HTTP/3")
    for key in ("min_version", "max_version"):
        if tls.get(key):
            if tls[key] not in ("1.2", "1.3"):
                invalid("tls." + key, "只接受 TLS 1.2/1.3")
            result[key] = tls[key]
    if "min_version" in result and "max_version" in result and result["min_version"] > result["max_version"]:
        invalid("tls", "最低版本不能大于最高版本")
    if tls.get("certificate"):
        certificate = tls["certificate"]
        if isinstance(certificate, list) and len(certificate) <= 8 and all(isinstance(item, str) for item in certificate):
            certificate = "\n".join(certificate)
        if not isinstance(certificate, str) or len(certificate.encode("utf-8")) > 65536 or "-----BEGIN CERTIFICATE-----" not in certificate:
            invalid("tls.certificate", "必须为大小受限的 PEM CA，不读取文件路径")
        try:
            ssl.create_default_context(cadata=certificate)
        except (ssl.SSLError, ValueError):
            invalid("tls.certificate", "PEM CA 无效")
        result["certificate"] = [certificate]
    reality = tls.get("reality") or {}
    if not isinstance(reality, dict) or set(reality) - {"enabled", "public_key", "short_id"}:
        invalid("tls.reality", "客户端 Reality 选项无效")
    if boolean(reality.get("enabled", False), "tls.reality.enabled"):
        if kind != "vless":
            invalid("tls.reality", "本版本仅验证 VLESS Reality")
        if not tls.get("server_name"):
            invalid("tls.server_name", "Reality 必须显式指定 SNI")
        try:
            ipaddress.ip_address(result["server_name"])
        except ValueError:
            pass
        else:
            invalid("tls.server_name", "Reality SNI 必须为域名")
        key = reality.get("public_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}=?", key):
            invalid("tls.reality.public_key", "必须为 X25519 公钥")
        try:
            decoded = base64.b64decode(key + "=" * (-len(key) % 4), altchars=b"-_", validate=True)
        except ValueError:
            invalid("tls.reality.public_key", "公钥编码无效")
        if len(decoded) != 32 or decoded in (bytes(32), b"\x01" + bytes(31)):
            invalid("tls.reality.public_key", "公钥长度或值无效")
        short_id = reality.get("short_id", "")
        if not isinstance(short_id, str) or len(short_id) > 16 or len(short_id) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", short_id):
            invalid("tls.reality.short_id", "必须为最多 8 字节的偶数位十六进制串")
        if result.get("certificate"):
            invalid("tls.reality", "Reality 公钥认证不能混用自定义 CA")
        result["reality"] = {"enabled": True, "public_key": base64.urlsafe_b64encode(decoded).decode().rstrip("="), "short_id": short_id.lower()}
    elif any(reality.get(key) for key in ("public_key", "short_id")):
        invalid("tls.reality.enabled", "不能静默丢弃已填写的 Reality 参数")
    utls = tls.get("utls") or {}
    if not isinstance(utls, dict) or set(utls) - {"enabled", "fingerprint"}:
        invalid("tls.utls", "客户端 TLS 选项无效")
    if "reality" in result and not boolean(utls.get("enabled", True), "tls.utls.enabled"):
        invalid("tls.utls.enabled", "Reality 需要兼容的 TLS ClientHello")
    if "reality" in result or boolean(utls.get("enabled", False), "tls.utls.enabled"):
        if kind not in ("vless", "vmess", "trojan"):
            invalid("tls.utls", "此协议未验证该 TLS 选项")
        fingerprint = utls.get("fingerprint") or "chrome"
        if not isinstance(fingerprint, str) or fingerprint not in FINGERPRINTS:
            invalid("tls.utls.fingerprint", "不支持该 ClientHello 类型")
        result["utls"] = {"enabled": True, "fingerprint": fingerprint}
    elif utls.get("fingerprint"):
        invalid("tls.utls.enabled", "不能静默丢弃已填写的 ClientHello 参数")
    return result


def transport_options(raw, kind, tls):
    value = raw.get("transport") or {}
    if not isinstance(value, dict):
        invalid("transport", "必须为对象")
    if not value:
        return None
    if kind not in ("vless", "vmess", "trojan") or value.get("type") not in ("ws", "grpc"):
        invalid("transport.type", "仅验证 WS 和 gRPC")
    if raw.get("flow"):
        invalid("flow", "Vision flow 不能与 WS/gRPC 混用")
    if value["type"] == "ws":
        if set(value) - {"type", "path", "headers", "max_early_data", "early_data_header_name"}:
            invalid("transport.ws", "包含不支持的选项")
        path = text(value.get("path") or "/", "transport.path", 2048, False)
        if not path.startswith("/") or "#" in path or " " in path:
            invalid("transport.path", "必须为有效请求路径")
        result = {"type": "ws", "path": path}
        headers = value.get("headers") or {}
        if not isinstance(headers, dict) or len(headers) > 16:
            invalid("transport.headers", "必须为大小受限的头部对象")
        seen = set()
        for key, item in headers.items():
            if not isinstance(key, str) or len(key) > 64 or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or key.lower() in seen:
                invalid("transport.headers", "头部名称无效或重复")
            seen.add(key.lower())
            text(item, "transport.headers", 2048)
        if headers:
            result["headers"] = dict(headers)
        if "max_early_data" in value:
            amount = integer(value["max_early_data"], "transport.max_early_data", 0, 65536)
            if amount:
                result["max_early_data"] = amount
                header = text(value.get("early_data_header_name") or "Sec-WebSocket-Protocol", "transport.early_data_header_name", 64, False)
                if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header):
                    invalid("transport.early_data_header_name", "头部名称无效")
                result["early_data_header_name"] = header
        elif value.get("early_data_header_name"):
            invalid("transport.max_early_data", "启用 early data 头部时必须填写有效大小")
        return result
    if set(value) - {"type", "service_name"}:
        invalid("transport.grpc", "包含不支持的选项")
    service = text(value.get("service_name", ""), "transport.service_name", 256)
    if " " in service or "?" in service or "#" in service:
        invalid("transport.service_name", "服务名称无效")
    if tls and tls.get("alpn") and "h2" not in tls["alpn"]:
        invalid("tls.alpn", "gRPC 需要 HTTP/2")
    return {"type": "grpc", "service_name": service}


def hysteria_options(raw):
    result = {}
    for key in ("up_mbps", "down_mbps"):
        if raw.get(key) is not None:
            result[key] = integer(raw[key], key, 1, 1000000)
    obfs = raw.get("obfs") or {}
    if not isinstance(obfs, dict) or set(obfs) - {"type", "password"}:
        invalid("obfs", "混淆选项无效")
    if obfs:
        if obfs.get("type") != "salamander":
            invalid("obfs.type", "本版本仅验证 salamander")
        result["obfs"] = {"type": "salamander", "password": text(obfs.get("password"), "obfs.password", 2048, False)}
    if any(raw.get(key) for key in ("server_ports", "hop_interval", "realm")):
        invalid("hysteria2", "本版本先验证固定服务器端口，不自动启用跳端口或 NAT rendezvous")
    return result
