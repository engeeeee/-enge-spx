"""Local, deliberately limited node import. Unsupported transports are rejected."""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import urllib.parse
import urllib.request
import uuid

from .state import SPXError, fingerprint
from . import __version__

MAX_IMPORT = 2 * 1024 * 1024
SS_METHODS = {"aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305", "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305"}


def unbase64(value: str) -> str:
    raw = value.strip().encode("ascii")
    return base64.b64decode(raw + b"=" * (-len(raw) % 4), altchars=b"-_", validate=True).decode("utf-8")


def truth(value) -> bool:
    return str(value).lower() in ("1", "true", "yes")


def normalize(value: dict, label: str = "") -> dict:
    if not isinstance(value, dict):
        raise ValueError("节点必须为对象")
    raw = dict(value.get("outbound", value))
    kind = str(raw.get("type", "")).lower()
    kind = {"ss": "shadowsocks", "socks5": "socks", "socks5h": "socks", "https": "http"}.get(kind, kind)
    if kind not in ("trojan", "vless", "vmess", "shadowsocks", "socks", "http"):
        raise ValueError("支持 SOCKS5、HTTP、HTTPS、Trojan、VLESS、VMess、Shadowsocks")
    if raw.get("transport") or raw.get("flow") or raw.get("plugin") or raw.get("multiplex"):
        raise ValueError("暂不支持 WS、gRPC、Reality、XTLS、插件或多路复用")
    if raw.get("network", "tcp") not in ("tcp", ""):
        raise ValueError("仅支持 TCP 节点")
    server = str(raw.get("server", raw.get("host", ""))).strip()
    if not server or len(server) > 253 or not re.fullmatch(r"[a-zA-Z0-9._:\-]+", server):
        raise ValueError("服务器地址无效")
    port = int(raw.get("server_port", raw.get("port", 0)))
    if not 1 <= port <= 65535:
        raise ValueError("服务器端口无效")
    outbound = {"type": kind, "tag": "selected", "server": server, "server_port": port}
    if kind != "http":
        outbound["network"] = "tcp"
    if kind in ("socks", "http"):
        if kind == "socks":
            if str(raw.get("version", "5")) != "5":
                raise ValueError("仅支持 SOCKS5 代理")
            outbound["version"] = "5"
        username, password = raw.get("username", ""), raw.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 1024 or len(password) > 2048:
            raise ValueError("代理认证信息无效")
        if password and not username:
            raise ValueError("填写代理密码时也需要用户名")
        if username:
            outbound.update({"username": username, "password": password})
    if kind in ("trojan", "shadowsocks"):
        password = raw.get("password")
        if not isinstance(password, str) or not password or len(password) > 2048:
            raise ValueError("节点密码为空或过长")
        outbound["password"] = password
    if kind in ("vless", "vmess"):
        outbound["uuid"] = str(uuid.UUID(str(raw.get("uuid", ""))))
    if kind == "vmess":
        if int(raw.get("alter_id", 0)) != 0:
            raise ValueError("仅支持 VMess AEAD（alterId=0）")
        security = raw.get("security", "auto")
        if security not in ("auto", "aes-128-gcm", "chacha20-poly1305", "none", "zero"):
            raise ValueError("VMess 加密方式不支持")
        outbound["security"] = security
    if kind == "shadowsocks":
        if raw.get("method") not in SS_METHODS:
            raise ValueError("仅支持 Shadowsocks AEAD / 2022 加密方式")
        outbound["method"] = raw["method"]
    tls = raw.get("tls", {"enabled": True} if str(raw.get("type", "")).lower() == "https" else {})
    if isinstance(tls, bool):
        tls = {"enabled": tls}
    if not isinstance(tls, dict):
        raise ValueError("TLS 配置无效")
    if truth(tls.get("insecure", False)):
        raise ValueError("此预览版要求校验 TLS 证书，不支持跳过校验")
    if any(tls.get(k) for k in ("reality", "utls", "ech", "certificate", "certificate_path", "certificate_public_key_sha256")):
        raise ValueError("此预览版暂不支持 Reality、uTLS、ECH 或自定义证书配置")
    enabled = truth(tls.get("enabled", kind in ("trojan", "vless")))
    if enabled and kind in ("socks", "shadowsocks"):
        raise ValueError("此协议暂不支持额外的 TLS 包装")
    if kind in ("trojan", "vless") and not enabled:
        raise ValueError("Trojan / VLESS 节点必须启用 TLS")
    if enabled:
        outbound["tls"] = {"enabled": True, "server_name": str(tls.get("server_name") or server)}
        if tls.get("alpn"):
            alpn = tls["alpn"]
            if not isinstance(alpn, list) or any(not isinstance(x, str) for x in alpn):
                raise ValueError("ALPN 必须为字符串列表")
            outbound["tls"]["alpn"] = alpn
    name = str(label or value.get("name") or value.get("label") or f"{kind} · {server}:{port}")
    return {"id": fingerprint(outbound)[:24], "label": name[:160], "outbound": outbound}


def uri_node(uri: str) -> dict:
    scheme = uri.split(":", 1)[0].lower()
    if scheme in ("socks5", "socks5h", "socks", "http", "https"):
        parsed = urllib.parse.urlsplit(uri)
        if not parsed.hostname or parsed.path not in ("", "/"):
            raise ValueError("代理地址格式：协议://用户名:密码@服务器:端口")
        query = urllib.parse.parse_qs(parsed.query)
        if set(query) - {"sni"}:
            raise ValueError("代理链接中包含暂不支持的参数")
        value = {"type": "socks" if scheme.startswith("socks") else "http", "server": parsed.hostname,
                 "server_port": parsed.port or (443 if scheme == "https" else 80 if scheme == "http" else 1080),
                 "username": urllib.parse.unquote(parsed.username or ""), "password": urllib.parse.unquote(parsed.password or "")}
        if scheme == "https":
            value["tls"] = {"enabled": True, "server_name": query.get("sni", [parsed.hostname])[0]}
        return normalize(value, urllib.parse.unquote(parsed.fragment))
    if scheme == "vmess":
        v = json.loads(unbase64(uri.split("://", 1)[1]))
        if v.get("tls", "") not in ("", "tls") or v.get("host") or v.get("path"):
            raise ValueError("VMess 的 TLS、Host 或 Path 参数暂不支持")
        if v.get("net", "tcp") != "tcp" or v.get("type", "none") not in ("none", ""):
            raise ValueError("VMess 仅支持无 HTTP 伪装的 TCP")
        return normalize({"type": "vmess", "server": v.get("add"), "server_port": v.get("port"), "uuid": v.get("id"), "alter_id": v.get("aid", 0), "security": v.get("scy", "auto"), "tls": {"enabled": v.get("tls") == "tls", "insecure": truth(v.get("allowInsecure", False)), "server_name": v.get("sni")}}, v.get("ps", ""))
    if scheme == "ss":
        content = uri[5:]
        body, _, fragment = content.partition("#")
        if "?" in body:
            body, query = body.split("?", 1)
            if urllib.parse.parse_qs(query).get("plugin"):
                raise ValueError("Shadowsocks 插件暂不支持")
        if "@" not in body:
            body = unbase64(body)
        credentials, target = body.rsplit("@", 1)
        if ":" not in credentials:
            credentials = unbase64(credentials)
        method, password = credentials.split(":", 1)
        parsed = urllib.parse.urlsplit("ss://" + target.rstrip("/"))
        return normalize({"type": "shadowsocks", "server": parsed.hostname, "server_port": parsed.port, "method": method, "password": urllib.parse.unquote(password)}, urllib.parse.unquote(fragment))
    parsed = urllib.parse.urlsplit(uri)
    if scheme not in ("trojan", "vless") or not parsed.hostname or parsed.username is None:
        raise ValueError("无法识别节点链接")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    q = lambda key, default="": query.get(key, [default])[0]
    if q("type", "tcp") != "tcp" or q("security", "tls") not in ("tls", "") or q("flow") or q("fp"):
        raise ValueError("此节点的传输、Reality、XTLS 或指纹参数暂不支持")
    value = {"type": scheme, "server": parsed.hostname, "server_port": parsed.port or 443, "tls": {"enabled": True, "server_name": q("sni") or q("peer") or parsed.hostname, "insecure": truth(q("allowInsecure") or q("insecure"))}}
    value["password" if scheme == "trojan" else "uuid"] = urllib.parse.unquote(parsed.username)
    if q("alpn"):
        value["tls"]["alpn"] = q("alpn").split(",")
    return normalize(value, urllib.parse.unquote(parsed.fragment))


def clash_node(v: dict) -> dict:
    if v.get("network", "tcp") != "tcp" or v.get("plugin") or v.get("reality-opts") or v.get("flow") or v.get("client-fingerprint"):
        raise ValueError("Clash 节点使用了暂不支持的传输选项")
    return normalize({"type": v.get("type"), "server": v.get("server"), "server_port": v.get("port"), "username": v.get("username", ""), "password": v.get("password", ""), "uuid": v.get("uuid"), "method": v.get("cipher"), "alter_id": v.get("alterId", 0), "security": v.get("cipher", "auto"), "tls": {"enabled": v.get("tls", v.get("type") in ("trojan", "vless", "https")), "server_name": v.get("servername") or v.get("sni"), "insecure": truth(v.get("skip-cert-verify", False))}}, v.get("name", ""))


def parse_nodes(text: str) -> tuple[list[dict], list[str]]:
    if len(text.encode("utf-8")) > MAX_IMPORT:
        raise SPXError("订阅或配置不能超过 2 MiB。")
    text = text.strip().lstrip("\ufeff")
    if not text:
        raise SPXError("请粘贴节点、订阅内容或选择配置文件。")
    nodes, errors = [], []
    try:
        if text.startswith(("{", "[")):
            obj = json.loads(text)
            rows = obj if isinstance(obj, list) else obj.get("nodes", [obj])
            parser = normalize
        elif "proxies:" in text:
            import yaml
            rows = yaml.safe_load(text).get("proxies", [])
            parser = clash_node
        else:
            if "://" not in text:
                text = unbase64(text)
            rows = [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith("#")]
            parser = uri_node
        if not isinstance(rows, list) or len(rows) > 2000:
            raise SPXError("节点列表无效或超过 2000 个节点。")
        for index, row in enumerate(rows):
            try:
                node = parser(row)
                if not any(x["id"] == node["id"] for x in nodes):
                    nodes.append(node)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                # Do not echo the input: subscription URLs and node credentials are secrets.
                reason = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else "格式无效"
                if not re.match(r"^[\u3400-\u9fff]|^(VMess|Trojan|Clash|ALPN|TLS) ", reason):
                    reason = "格式无效"
                if len(reason) > 120 or "uuid" in reason.lower() or "base64" in reason.lower():
                    reason = "格式无效"
                errors.append(f"第 {index + 1} 项：{reason}")
    except SPXError:
        raise
    except Exception as error:
        raise SPXError("无法解析配置，请使用节点 URI、JSON 或 Clash proxies。") from error
    if not nodes:
        raise SPXError("没有可用节点。" + (errors[0] if errors else ""))
    return nodes, errors


def fetch_subscription(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SPXError("订阅地址必须为 HTTPS，且不能在地址中携带用户名和密码。")
    class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urllib.parse.urlsplit(newurl).scheme != "https":
                raise SPXError("订阅重定向到了非 HTTPS 地址，已停止下载。")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ENGE-SPX/" + __version__})
        with urllib.request.build_opener(HTTPSRedirect).open(request, timeout=25) as response:
            data = response.read(MAX_IMPORT + 1)
        if len(data) > MAX_IMPORT:
            raise SPXError("订阅超过 2 MiB。")
        return data.decode("utf-8-sig")
    except SPXError:
        raise
    except Exception as error:
        raise SPXError("订阅下载失败，请检查地址和本机网络。") from error
