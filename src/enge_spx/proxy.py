"""Explicit landing/line proxy configuration; no global proxy changes."""
import ipaddress
import os
import urllib.parse

from .nodes import normalize, uri_node
from .state import SPXError


def protocol(node):
    value = node.get("outbound", node)
    kind = value["type"]
    return "HTTPS" if kind == "http" and value.get("tls", {}).get("enabled") else "SOCKS5" if kind == "socks" else kind.upper()


def loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def relay_config(enabled=False, url="", downloads=True):
    if not enabled:
        return {"enabled": False, "downloads": bool(downloads)}
    try:
        node = uri_node(url.strip())
        value = node["outbound"]
        if value["type"] not in ("socks", "http") or not loopback(value["server"]):
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise SPXError("本机线路请填写回环代理地址，例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080。") from error
    return {"enabled": True, "outbound": value, "downloads": bool(downloads)}


def validate_relay(config):
    return relay_config(bool(config.get("enabled")), proxy_url(config) or "", config.get("downloads", True))


def proxy_url(config):
    if not config.get("enabled"):
        return None
    value = normalize(config["outbound"])["outbound"]
    scheme = "socks5" if value["type"] == "socks" else "https" if value.get("tls", {}).get("enabled") else "http"
    auth = ""
    if value.get("username"):
        auth = urllib.parse.quote(value["username"], safe="") + ":" + urllib.parse.quote(value.get("password", ""), safe="") + "@"
    host = value["server"]
    if ":" in host:
        host = "[" + host + "]"
    return f"{scheme}://{auth}{host}:{value['server_port']}"


def detect_system_proxy():
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                server = str(winreg.QueryValueEx(key, "ProxyServer")[0])
                if enabled and server:
                    if ";" in server or "=" in server:
                        values = dict(part.split("=", 1) for part in server.split(";") if "=" in part)
                        candidate = values.get("http") or values.get("https")
                        if candidate:
                            return "http://" + candidate
                        if values.get("socks"):
                            return "socks5://" + values["socks"]
                    return server if "://" in server else "http://" + server
        except OSError:
            pass
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        value = os.environ.get(name)
        if value:
            try:
                relay_config(True, value)
                return value
            except SPXError:
                pass
    raise SPXError("没有读到本机回环代理。请手动填写线路客户端的 HTTP 或 SOCKS5 监听地址。")
