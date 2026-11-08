"""Compose a fixed, authenticated first hop; keep diagnostics off the work network."""
from __future__ import annotations

from copy import deepcopy
import ipaddress

from .nodes import normalize
from .proxy import loopback, validate_relay
from .state import SPXError

LINE_MODES = {"软件内双跳（推荐）": "managed", "本机代理（v2ray 兼容）": "local"}
LINE_CHECK = "spx-line-check"
LINE_PROXY = "http://127.0.0.1:2082"


class LineSecurityError(SPXError):
    pass


LINE_CHECK_CODE = '''import ipaddress,json,os,urllib.request
for name in tuple(os.environ):
 if name.lower() in ('http_proxy','https_proxy','all_proxy','no_proxy'): os.environ.pop(name,None)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':'http://127.0.0.1:2082','https':'http://127.0.0.1:2082'}))
addresses=[]
for url in ('https://api.ipify.org?format=json','https://checkip.amazonaws.com'):
 with opener.open(url,timeout=10) as response:
  raw=response.read(32768).decode('utf-8')
 value=json.loads(raw)['ip'] if 'ipify' in url else raw.strip()
 address=ipaddress.IPv4Address(value)
 if not address.is_global: raise ValueError('non-public exit')
 addresses.append(str(address))
if len(set(addresses))!=1: raise ValueError('line exits disagree')
print(json.dumps({'ip':addresses[0],'sources':['api.ipify.org','checkip.amazonaws.com']}))
'''


def managed_line(node: dict, server_ip="") -> dict:
    value = deepcopy(normalize(node["outbound"], node["label"])["outbound"])
    encrypted = value["type"] in ("trojan", "vless", "shadowsocks") or value.get("tls", {}).get("enabled") or value["type"] == "vmess" and value.get("security", "auto") not in ("none", "zero")
    if not encrypted:
        raise SPXError("软件内双跳的线路需使用加密节点（SS、Trojan、TLS VLESS、加密 VMess 或 HTTPS）；普通 SOCKS5/HTTP 可作为落地。")
    try:
        address = ipaddress.IPv4Address(server_ip or value["server"])
        if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            raise ValueError()
    except ValueError as error:
        raise SPXError("线路节点使用域名时，请填写其服务器 IPv4；软件内双跳不会通过本机 DNS 查询节点。") from error
    value.update(tag="spx-line", server=str(address), connect_timeout="10s")
    return value


def chain_outbounds(landing: dict, relay: dict, line_node=None):
    relay = validate_relay(relay)
    selected = deepcopy(landing["outbound"])
    if not relay["enabled"]:
        return [selected], None
    if loopback(selected["server"]):
        raise SPXError("启用前置线路时，落地请使用远端节点。")
    if relay["mode"] == "managed":
        if not line_node or landing["id"] == line_node["id"]:
            raise SPXError("线路和落地必须选择不同节点。")
        line = managed_line(line_node, relay["server_ip"])
        if (line["server"], line["server_port"]) == (selected["server"], selected["server_port"]):
            raise SPXError("线路和落地不能使用同一个服务器端口。")
        selected["detour"] = "spx-line"
        return [selected, line], None
    middle = deepcopy(relay["outbound"])
    target = {"host": middle["server"], "port": middle["server_port"]}
    middle.update(tag="host-line", server="127.0.0.1", server_port=2081)
    selected["detour"] = "host-line"
    return [selected, middle], target


def line_rules(outbounds):
    return [{"inbound": [LINE_CHECK], "action": "route", "outbound": outbounds[1]["tag"]}]


def v2ray_rules(node):
    value = node["outbound"]
    rule = {"remarks": "ENGE SPX 落地必须走线路：请置于直连规则之前", "outboundTag": "proxy", "enabled": True, "port": str(value["server_port"])}
    try:
        address = ipaddress.ip_address(value["server"])
        rule["ip"] = [str(address) + ("/32" if address.version == 4 else "/128")]
    except ValueError:
        rule["domain"] = ["full:" + value["server"]]
    return [rule, {"remarks": "ENGE SPX 线路出口检查必须走线路", "outboundTag": "proxy", "enabled": True, "domain": ["full:api.ipify.org", "full:checkip.amazonaws.com"]}]
