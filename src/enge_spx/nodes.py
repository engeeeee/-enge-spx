"""Bounded node import; retain canonical legacy IDs and reject unsafe options."""
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
from .node_options import tls_options, transport_options, hysteria_options, invalid, integer, text as bounded_text, NodeParameterError

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
    source = value.get("outbound", value)
    if not isinstance(source, dict):
        invalid("outbound", "节点必须为对象")
    raw = dict(source)
    allowed = {"type", "tag", "server", "host", "server_port", "port", "network", "tls", "transport", "flow", "plugin", "multiplex", "username", "password", "version", "uuid", "alter_id", "security", "method", "up_mbps", "down_mbps", "obfs", "server_ports", "hop_interval", "realm", "id", "label", "name", "data", "udp"}
    if set(raw) - allowed:
        invalid("outbound", "包含未验证的参数、路径或链路覆盖")
    kind = str(raw.get("type", "")).lower()
    kind = {"ss": "shadowsocks", "socks5": "socks", "socks5h": "socks", "https": "http", "hy2": "hysteria2"}.get(kind, kind)
    if kind not in ("trojan", "vless", "vmess", "shadowsocks", "socks", "http", "hysteria2"):
        raise ValueError("支持 SOCKS5、HTTP(S)、Trojan、VLESS、VMess、Shadowsocks 和 Hysteria2")
    if raw.get("plugin") or raw.get("multiplex"):
        invalid("outbound", "不支持插件或多路复用")
    if raw.get("network", "tcp") not in ("tcp", "", "udp") or kind != "hysteria2" and raw.get("network") == "udp":
        invalid("network", "此协议或网络类型未验证")
    server = raw.get("server", raw.get("host", ""))
    if not isinstance(server, str):
        invalid("server", "必须为服务器地址")
    server = server.strip()
    if not server or len(server) > 253 or not re.fullmatch(r"[a-zA-Z0-9._:\-]+", server):
        raise ValueError("服务器地址无效")
    port = integer(raw.get("server_port", raw.get("port", 0)), "server_port", 1, 65535)
    outbound = {"type": kind, "tag": "selected", "server": server, "server_port": port}
    if kind not in ("http", "hysteria2"):
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
    if kind in ("trojan", "shadowsocks", "hysteria2"):
        password = raw.get("password")
        if not isinstance(password, str) or not password or len(password) > 2048:
            raise ValueError("节点密码为空或过长")
        outbound["password"] = password
    if kind in ("vless", "vmess"):
        try:
            outbound["uuid"] = str(uuid.UUID(str(raw.get("uuid", ""))))
        except (ValueError, TypeError, AttributeError):
            invalid("uuid", "标识符格式无效")
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
    tls = tls_options(raw, kind, server)
    if tls:
        outbound["tls"] = tls
    transport = transport_options(raw, kind, tls)
    if transport:
        outbound["transport"] = transport
    if raw.get("flow"):
        if kind != "vless" or raw["flow"] != "xtls-rprx-vision" or transport:
            invalid("flow", "只支持 VLESS TCP 的 xtls-rprx-vision")
        outbound["flow"] = raw["flow"]
    if kind == "hysteria2":
        outbound.update(hysteria_options(raw))
        if raw.get("network"):
            outbound["network"] = raw["network"]
    name = bounded_text(label or value.get("name") or value.get("label") or f"{kind} · {server}:{port}", "label", 4096)
    return {"id": fingerprint(outbound)[:24], "label": name[:160], "outbound": outbound}


def uri_node(uri: str) -> dict:
    scheme = uri.split(":", 1)[0].lower()
    if scheme in ("socks5", "socks5h", "socks", "http", "https"):
        parsed = urllib.parse.urlsplit(uri)
        if not parsed.hostname or parsed.path not in ("", "/"):
            raise ValueError("代理地址格式：协议://用户名:密码@服务器:端口")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if set(query) - {"sni"} or any(len(items) != 1 for items in query.values()):
            raise ValueError("代理链接中包含暂不支持的参数")
        value = {"type": "socks" if scheme.startswith("socks") else "http", "server": parsed.hostname,
                 "server_port": parsed.port or (443 if scheme == "https" else 80 if scheme == "http" else 1080),
                 "username": urllib.parse.unquote(parsed.username or ""), "password": urllib.parse.unquote(parsed.password or "")}
        if scheme == "https":
            value["tls"] = {"enabled": True, "server_name": query.get("sni", [parsed.hostname])[0]}
        return normalize(value, urllib.parse.unquote(parsed.fragment))
    if scheme == "vmess":
        v = json.loads(unbase64(uri.split("://", 1)[1]))
        if v.get("tls", "") not in ("", "tls") or v.get("type", "none") not in ("none", ""):
            invalid("vmess", "只支持 AEAD 与已验证的 TLS/传输参数")
        value = {"type": "vmess", "server": v.get("add"), "server_port": v.get("port"), "uuid": v.get("id"), "alter_id": v.get("aid", 0), "security": v.get("scy", "auto"), "tls": {"enabled": v.get("tls") == "tls", "insecure": truth(v.get("allowInsecure", False)), "server_name": v.get("sni")}}
        network = v.get("net", "tcp")
        if network == "ws":
            value["transport"] = {"type": "ws", "path": v.get("path") or "/", "headers": {"Host": v["host"]} if v.get("host") else {}}
        elif network == "grpc":
            if v.get("host"):
                invalid("transport.grpc", "不支持额外 authority 覆盖")
            value["transport"] = {"type": "grpc", "service_name": v.get("path") or ""}
        elif network != "tcp" or v.get("path") or v.get("host"):
            invalid("transport.type", "不支持此传输或 TCP 伪装参数")
        if v.get("fp"):
            value["tls"]["utls"] = {"enabled": True, "fingerprint": v["fp"]}
        return normalize(value, v.get("ps", ""))
    if scheme == "ss":
        content = uri[5:]
        body, _, fragment = content.partition("#")
        if "?" in body:
            body, query = body.split("?", 1)
            options = urllib.parse.parse_qs(query, keep_blank_values=True)
            if set(options) - {"plugin"}:
                invalid("uri.query", "Shadowsocks 包含未验证的参数")
            if options.get("plugin"):
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
    if scheme not in ("trojan", "vless", "hysteria2", "hy2") or not parsed.hostname or parsed.username is None or parsed.path not in ("", "/"):
        raise ValueError("无法识别节点链接")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if any(len(items) != 1 for items in query.values()):
        invalid("uri.query", "不接受重复参数")
    q = lambda key, default="": query.get(key, [default])[0]
    if q("sni") and q("peer") and q("sni") != q("peer"):
        invalid("tls.server_name", "SNI 参数冲突")
    value = {"type": "hysteria2" if scheme == "hy2" else scheme, "server": parsed.hostname, "server_port": parsed.port or 443, "tls": {"enabled": True, "server_name": q("sni") or q("peer") or parsed.hostname, "insecure": truth(q("allowInsecure")) or truth(q("insecure"))}}
    credentials = urllib.parse.unquote(parsed.netloc.rsplit("@", 1)[0])
    value["uuid" if scheme == "vless" else "password"] = credentials
    if q("alpn"):
        value["tls"]["alpn"] = q("alpn").split(",")
    if scheme in ("hysteria2", "hy2"):
        if set(query) - {"sni", "peer", "insecure", "allowInsecure", "alpn", "obfs", "obfs-password", "upmbps", "downmbps"}:
            invalid("uri.query", "Hysteria2 包含未验证的参数")
        if q("obfs"):
            value["obfs"] = {"type": q("obfs"), "password": q("obfs-password")}
        elif q("obfs-password"):
            invalid("obfs.type", "混淆密码缺少对应类型")
        for source, target in (("upmbps", "up_mbps"), ("downmbps", "down_mbps")):
            if q(source):
                value[target] = q(source)
        return normalize(value, urllib.parse.unquote(parsed.fragment))
    if set(query) - {"sni", "peer", "allowInsecure", "insecure", "alpn", "type", "security", "encryption", "flow", "fp", "pbk", "sid", "path", "host", "serviceName", "service_name", "mode", "ed", "eh", "spx"}:
        invalid("uri.query", "包含未验证的参数")
    security, transport = q("security", "tls"), q("type", "tcp")
    if security not in ("", "tls", "reality") or q("encryption", "none") not in ("", "none"):
        invalid("uri.security", "此安全或加密扩展未验证")
    if q("spx") not in ("", "/"):
        invalid("uri.spx", "只接受默认探测元数据，不启用额外探测行为")
    if security == "reality":
        value["tls"]["server_name"] = q("sni") or q("peer")
        value["tls"]["reality"] = {"enabled": True, "public_key": q("pbk"), "short_id": q("sid")}
    elif q("pbk") or q("sid"):
        invalid("tls.reality", "公钥和 short ID 需要显式 Reality 模式")
    if q("fp"):
        value["tls"]["utls"] = {"enabled": True, "fingerprint": q("fp")}
    if q("flow"):
        value["flow"] = q("flow")
    if transport == "ws":
        if q("serviceName") or q("service_name") or q("mode"):
            invalid("transport.ws", "不能混用 gRPC 参数")
        value["transport"] = {"type": "ws", "path": q("path") or "/", "headers": {"Host": q("host")} if q("host") else {}}
        if q("ed"):
            value["transport"].update(max_early_data=q("ed"), early_data_header_name=q("eh") or "Sec-WebSocket-Protocol")
        elif q("eh"):
            invalid("transport.max_early_data", "early data 头部缺少大小参数")
    elif transport == "grpc":
        if q("host") or q("path") or q("ed") or q("eh") or q("mode") not in ("", "gun"):
            invalid("transport.grpc", "不支持额外 authority、WS 或 multi-mode 参数")
        if q("serviceName") and q("service_name") and q("serviceName") != q("service_name"):
            invalid("transport.service_name", "服务名称参数冲突")
        value["transport"] = {"type": "grpc", "service_name": q("serviceName") or q("service_name")}
    elif transport != "tcp" or any(q(key) for key in ("host", "path", "ed", "eh", "serviceName", "service_name", "mode")):
        invalid("transport.type", "不支持此传输或 TCP 伪装参数")
    return normalize(value, urllib.parse.unquote(parsed.fragment))


def clash_node(v: dict) -> dict:
    if not isinstance(v, dict):
        invalid("clash.proxy", "节点必须为对象")
    if any(v.get(key) for key in ("plugin", "smux", "shadow-tls-opts", "restls-opts", "jls-opts", "ech-opts", "private-key", "encryption", "ca", "dialer-proxy")):
        invalid("clash.proxy", "含未验证的扩展、路径或外部链路配置")
    known = {"name", "type", "server", "port", "username", "password", "uuid", "cipher", "alterId", "tls", "skip-cert-verify", "servername", "sni", "alpn", "ca-str", "reality-opts", "client-fingerprint", "fingerprint", "flow", "network", "ws-opts", "grpc-opts", "obfs", "obfs-password", "up", "down", "ports", "hop-interval", "udp", "plugin", "smux", "dialer-proxy", "encryption", "ca", "private-key", "shadow-tls-opts", "restls-opts", "jls-opts", "ech-opts"}
    if set(v) - known:
        invalid("clash.proxy", "包含未验证的选项，不会静默修改链路行为")
    kind = str(v.get("type", "")).lower()
    value = {"type": kind, "server": v.get("server"), "server_port": v.get("port"), "username": v.get("username", ""), "password": v.get("password", ""), "uuid": v.get("uuid"), "method": v.get("cipher"), "alter_id": v.get("alterId", 0), "security": v.get("cipher", "auto"), "tls": {"enabled": v.get("tls", kind in ("trojan", "vless", "https", "hysteria2", "hy2")), "server_name": v.get("servername") or v.get("sni"), "insecure": truth(v.get("skip-cert-verify", False))}}
    if v.get("alpn"):
        value["tls"]["alpn"] = v["alpn"]
    if v.get("ca-str"):
        value["tls"]["certificate"] = v["ca-str"]
    if v.get("reality-opts"):
        reality = v["reality-opts"]
        if not isinstance(reality, dict) or set(reality) - {"public-key", "short-id"}:
            invalid("clash.reality-opts", "不支持此 Reality 扩展")
        value["tls"]["reality"] = {"enabled": True, "public_key": reality.get("public-key"), "short_id": reality.get("short-id", "")}
    if v.get("client-fingerprint"):
        value["tls"]["utls"] = {"enabled": True, "fingerprint": v["client-fingerprint"]}
    if v.get("fingerprint"):
        invalid("clash.fingerprint", "证书 pinning 尚未验证，不会把它当作 ClientHello 参数")
    if v.get("flow"):
        value["flow"] = v["flow"]
    network = v.get("network", "tcp")
    if network == "ws":
        options = v.get("ws-opts") or {}
        if not isinstance(options, dict) or set(options) - {"path", "headers", "max-early-data", "early-data-header-name"}:
            invalid("clash.ws-opts", "含未验证的 WS 参数")
        value["transport"] = {"type": "ws", "path": options.get("path") or "/", "headers": options.get("headers") or {}}
        if options.get("max-early-data"):
            value["transport"].update(max_early_data=options["max-early-data"], early_data_header_name=options.get("early-data-header-name") or "Sec-WebSocket-Protocol")
    elif network == "grpc":
        options = v.get("grpc-opts") or {}
        if not isinstance(options, dict) or set(options) - {"grpc-service-name"}:
            invalid("clash.grpc-opts", "含未验证的 gRPC 参数")
        value["transport"] = {"type": "grpc", "service_name": options.get("grpc-service-name") or ""}
    elif network != "tcp" or v.get("ws-opts") or v.get("grpc-opts"):
        invalid("clash.network", "此传输尚未验证或与参数冲突")
    if kind in ("hy2", "hysteria2"):
        for source, target in (("up", "up_mbps"), ("down", "down_mbps")):
            if v.get(source) is not None:
                amount = v[source]
                if isinstance(amount, str):
                    amount = re.sub(r"(?i)\s*mbps\s*$", "", amount.strip())
                value[target] = amount
        if v.get("obfs"):
            value["obfs"] = {"type": v["obfs"], "password": v.get("obfs-password", "")}
        if v.get("ports") or v.get("hop-interval"):
            invalid("clash.ports", "本版本先验证固定服务器端口")
    return normalize(value, v.get("name", ""))


def parse_nodes(text: str) -> tuple[list[dict], list[str]]:
    if len(text.encode("utf-8")) > MAX_IMPORT:
        raise SPXError("订阅或配置不能超过 2 MiB。")
    text = text.strip().lstrip("\ufeff")
    if not text:
        raise SPXError("请粘贴节点、订阅内容或选择配置文件。")
    nodes, errors = [], []
    try:
        if not text.startswith(("{", "[")) and "://" not in text and not re.search(r"(?m)^\s*(proxies|proxy-providers)\s*:", text):
            text = unbase64(text).strip().lstrip("\ufeff")
        if text.startswith(("{", "[")):
            obj = json.loads(text)
            if isinstance(obj, dict) and "proxies" in obj:
                rows, parser = obj["proxies"], clash_node
                if any(key in obj for key in ("rules", "proxy-groups", "proxy-providers", "dns", "external-controller")):
                    errors.append("配置仅导入 proxies 节点；不执行规则、自动选择、DNS 或远程 provider。")
            else:
                rows = obj if isinstance(obj, list) else obj.get("nodes", obj.get("outbounds", [obj]))
                parser = normalize
        elif re.search(r"(?m)^\s*(proxies|proxy-providers)\s*:", text):
            import yaml
            obj = yaml.safe_load(text)
            if not isinstance(obj, dict):
                invalid("clash", "配置必须为对象")
            rows = obj.get("proxies", [])
            parser = clash_node
            if any(key in obj for key in ("rules", "proxy-groups", "proxy-providers", "dns", "external-controller")):
                errors.append("配置仅导入 proxies 节点；不执行规则、自动选择、DNS 或远程 provider。需要订阅时请通过订阅入口主动获取。")
        else:
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
                if not isinstance(error, NodeParameterError) and not re.match(r"^[\u3400-\u9fff]|^(VMess|Trojan|Clash|ALPN|TLS) ", reason):
                    reason = "格式无效"
                if len(reason) > 120 or not isinstance(error, NodeParameterError) and ("uuid" in reason.lower() or "base64" in reason.lower()):
                    reason = "格式无效"
                errors.append(f"第 {index + 1} 项：{reason}")
    except SPXError:
        raise
    except Exception as error:
        raise SPXError("无法解析配置，请使用节点 URI、JSON 或 Clash proxies。") from error
    if not nodes:
        raise SPXError("没有可用节点。" + (errors[0] if errors else ""))
    return nodes, errors


def fetch_subscription(url: str, proxy=None) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SPXError("订阅地址必须为 HTTPS，且不能在地址中携带用户名和密码。")
    try:
        from .downloads import client
        def https_only(request):
            if request.url.scheme != "https":
                raise SPXError("订阅重定向到了非 HTTPS 地址，已停止下载。")
        with client(proxy) as session:
            session.event_hooks["request"].append(https_only)
            with session.stream("GET", url, headers={"User-Agent": "ENGE-SPX/" + __version__}) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes(65536):
                    data.extend(chunk)
                    if len(data) > MAX_IMPORT:
                        raise SPXError("订阅超过 2 MiB。")
                return data.decode("utf-8-sig")
    except SPXError:
        raise
    except Exception as error:
        raise SPXError("订阅下载失败，请检查地址和本机网络。") from error
