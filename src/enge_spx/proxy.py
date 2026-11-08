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


def relay_config(enabled=False, url="", downloads=True, mode="local", line_id="", server_ip="", expected_ip=""):
    if not enabled:
        return {"enabled": False, "downloads": bool(downloads)}
    if mode not in ("local", "managed"):
        raise SPXError("请选择本机代理兼容模式或软件内双跳。")
    try:
        expected_ip = str(ipaddress.IPv4Address(expected_ip.strip())) if expected_ip.strip() else ""
        if expected_ip and not ipaddress.ip_address(expected_ip).is_global:
            raise ValueError()
        server_ip = str(ipaddress.IPv4Address(server_ip.strip())) if server_ip.strip() else ""
    except (ValueError, AttributeError) as error:
        raise SPXError("线路服务器地址应为 IPv4；锁定的线路出口应为公网 IPv4。") from error
    result = {"enabled": True, "mode": mode, "downloads": bool(downloads), "expected_ip": expected_ip}
    if mode == "managed":
        if not isinstance(line_id, str) or not line_id:
            raise SPXError("请先导入并选择线路节点；落地节点在上方单独选择。")
        result.update(line_id=line_id, server_ip=server_ip)
        if not url.strip():
            return result
    try:
        node = uri_node(url.strip())
        value = node["outbound"]
        if value["type"] not in ("socks", "http") or not loopback(value["server"]):
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise SPXError("本机线路请填写回环代理地址，例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080。") from error
    result["outbound" if mode == "local" else "download_outbound"] = value
    return result


def validate_relay(config):
    return relay_config(bool(config.get("enabled")), proxy_url(config) or "", config.get("downloads", True), config.get("mode", "local"), config.get("line_id", ""), config.get("server_ip", ""), config.get("expected_ip", ""))


def route_config(config):
    return {k: v for k, v in validate_relay(config).items() if k not in ("downloads", "download_outbound")}


def proxy_url(config):
    if not config.get("enabled"):
        return None
    value = config.get("download_outbound") if config.get("mode") == "managed" else config.get("outbound")
    if not value:
        return None
    value = normalize(value)["outbound"]
    scheme = "socks5" if value["type"] == "socks" else "https" if value.get("tls", {}).get("enabled") else "http"
    auth = ""
    if value.get("username"):
        auth = urllib.parse.quote(value["username"], safe="") + ":" + urllib.parse.quote(value.get("password", ""), safe="") + "@"
    host = value["server"]
    if ":" in host:
        host = "[" + host + "]"
    return f"{scheme}://{auth}{host}:{value['server_port']}"


def download_proxy(config):
    if not config.get("downloads", True):
        return None, "直接连接"
    if config.get("enabled") and proxy_url(config):
        url, origin = proxy_url(config), "已配置的本机代理"
    else:
        try:
            detected = relay_config(True, detect_system_proxy())
            url, origin = proxy_url(detected), "系统本机代理"
        except SPXError as error:
            raise SPXError("已要求通过本机代理下载，但未检测到可用的回环代理。请填写 v2ray 的 HTTP/SOCKS 监听地址，或主动取消“下载运行环境时使用本机代理”后直连下载。") from error
    parsed = urllib.parse.urlsplit(url)
    # Deliberately exclude user info when reporting the chosen download route.
    return url, f"{origin} {parsed.scheme}://{parsed.hostname}:{parsed.port}"


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
