"""Scrub application-owned diagnostics; interactive tool stdio stays untouched."""
import re
import urllib.parse

KEYS = {"password", "uuid", "token", "browser_token", "control", "secret", "private_key", "authorization", "proxy-authorization"}


def values(value):
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in KEYS and isinstance(item, str) and item:
                result.add(item)
            result.update(values(item))
    elif isinstance(value, list):
        for item in value:
            result.update(values(item))
    elif isinstance(value, str) and "://" in value:
        try:
            parsed = urllib.parse.urlsplit(value)
            if parsed.password:
                result.update((parsed.password, urllib.parse.unquote(parsed.password)))
        except ValueError:
            pass
    return result


def redact(text, secrets=()):
    text = str(text)
    text = re.sub(r"(?i)\b((?:https?|socks5h?|socks|trojan|vless|ss|vmess)://)[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r'''(?i)(["']?(?:password|uuid|token|browser_token|control|secret|private_key|authorization|proxy-authorization)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;\r\n}]+)''', r'\1"[REDACTED]"', text)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            for encoded in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
                text = text.replace(encoded, "[REDACTED]")
    return text
