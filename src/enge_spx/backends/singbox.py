"""Generate only a fixed sing-box chain; never accept imported routing policy."""
from copy import deepcopy

from ..state import SPXError


class SingBoxBackend:
    name = "sing-box"
    version = "1.14.3"
    image = "ghcr.io/sagernet/sing-box:v" + version
    protocols = frozenset({"socks", "http", "shadowsocks", "trojan", "vless", "vmess", "hysteria2"})

    def gateway_config(self, outbounds, listen, chained):
        from ..line_security import LINE_CHECK, line_rules
        values = deepcopy(outbounds)
        if len(values) != (2 if chained else 1) or any(item.get("type") not in self.protocols for item in values):
            raise SPXError("代理配置必须是受支持的固定链路，不能使用 DIRECT、自动选择或测速回退。")
        if values[0].get("tag") != "selected":
            raise SPXError("最终出口标签无效。")
        if chained:
            if values[1].get("tag") not in ("spx-line", "host-line") or values[0].get("detour") != values[1]["tag"] or values[1].get("detour"):
                raise SPXError("线路和落地引用不符合固定链路要求。")
            if values[0]["type"] == "hysteria2":
                raise SPXError("Hysteria2 落地需要 UDP 承载，当前前置转发组合未验证。请将 Hysteria2 用作线路并选择 SOCKS5/HTTP(S) 落地，或单独使用 Hysteria2；不会回退直连。")
        elif values[0].get("detour"):
            raise SPXError("单出口配置不能引用未确认的前置线路。")
        config = {"log": {"level": "warn"}, "inbounds": [{"type": "mixed", "tag": "clients", "listen": listen, "listen_port": 2080}], "outbounds": values, "route": {"final": "selected"}}
        if chained:
            config["inbounds"].append({"type": "mixed", "tag": LINE_CHECK, "listen": "127.0.0.1", "listen_port": 2082})
            config["route"]["rules"] = line_rules(values)
        return config
