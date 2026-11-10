"""Proxy core adapters; runtime trust and shutdown remain in Engine."""
from typing import Protocol

from ..state import SPXError
from .singbox import SingBoxBackend


class ProxyBackendAdapter(Protocol):
    name: str
    version: str
    image: str

    def gateway_config(self, outbounds: list[dict], listen: str, chained: bool) -> dict: ...


DEFAULT_BACKEND = SingBoxBackend()


def get_backend(name=None) -> ProxyBackendAdapter:
    if name in (None, "", "sing-box"):
        return DEFAULT_BACKEND
    raise SPXError("此代理后端尚未实现；不会自动切换后端或直连。")
