"""Resumable, digest-verified release downloads with explicit proxy selection."""
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from . import __version__
from .state import SPXError
from .brand import PROJECT_URL

RELEASE = PROJECT_URL + "/releases/download/v" + __version__ + "-windows/"


class DownloadPaused(SPXError):
    pass


def client(proxy=None, transport=None):
    import httpx
    def secure(request):
        if request.url.scheme != "https" and request.url.host not in ("127.0.0.1", "localhost"):
            raise SPXError("下载地址必须使用 HTTPS。")
    return httpx.Client(proxy=proxy, transport=transport, trust_env=False, follow_redirects=True,
                        timeout=httpx.Timeout(20, read=25), event_hooks={"request": [secure]})


def network_error(error, stage):
    import httpx
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        reason = "本版本文件暂不可用" if status == 404 else "下载服务拒绝请求或正在限流" if status in (403, 429) else "下载服务返回错误"
        return SPXError(f"{stage}失败：{reason}（HTTP {status}）。请检查本机代理，稍后重试。")
    if isinstance(error, httpx.TimeoutException):
        return SPXError(f"{stage}超时。请在“连接与代理”检查本机代理，开启“下载运行环境时使用本机代理”后重试。")
    if isinstance(error, httpx.ProxyError):
        return SPXError(f"{stage}失败：无法连接本机下载代理，请检查线路客户端、监听端口和代理认证。")
    return SPXError(f"{stage}失败：无法建立 HTTPS 连接（{type(error).__name__}）。请检查网络、本机代理和系统时间。")


def manifest(platform, recipes, proxy=None):
    import httpx
    filename = "ENGE-SPX-Runtime-" + platform.replace("/", "-") + "-" + __version__ + ".json"
    try:
        with client(proxy) as session:
            response = session.get(RELEASE + filename)
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError()
            value = response.json()
        if value["schema"] != 1 or value["version"] != __version__ or value["platform"] != platform or value["recipes"] != recipes:
            raise ValueError()
        if set(value["images"]) != {"gateway", "work", "browser"} or not all(re.fullmatch(r"sha256:[a-f0-9]{64}", x) for x in value["images"].values()):
            raise ValueError()
        if set(value["image_configs"]) != set(value["images"]) or not all(re.fullmatch(r"sha256:[a-f0-9]{64}", x) for x in value["image_configs"].values()):
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{64}", value["sha256"]) or not 0 < int(value["bytes"]) < 2 * 1024**3:
            raise ValueError()
        expected = "ENGE-SPX-Runtime-" + platform.replace("/", "-") + "-" + __version__ + ".tar.gz"
        if value["filename"] != expected:
            raise ValueError()
        return value
    except SPXError:
        raise
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        raise network_error(error, "获取运行环境信息") from error
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
        raise SPXError("运行环境清单与当前程序不匹配或格式异常，请确认使用同一版本的程序和环境包。") from error


def digest(path, cancel=None):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while data := stream.read(1024 * 1024):
            if cancel and cancel.is_set():
                raise DownloadPaused("已暂停，已下载的部分会保留。")
            result.update(data)
    return result.hexdigest()


def download(url, target, sha256, size, progress=lambda data: None, cancel=None, proxy=None, transport=None):
    import httpx
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    if target.exists():
        if target.stat().st_size == size and digest(target, cancel) == sha256:
            return target
        target.unlink()
    if part.exists() and part.stat().st_size > size:
        part.unlink()
    for attempt in range(4):
        if cancel and cancel.is_set():
            raise DownloadPaused("下载已暂停，重新点击安装即可续传。")
        offset = part.stat().st_size if part.exists() else 0
        if offset == size:
            break
        started = time.monotonic()
        last = 0
        try:
            with client(proxy, transport) as session:
                with session.stream("GET", url, headers={"Range": f"bytes={offset}-"} if offset else {}) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        content_range = response.headers.get("Content-Range", "")
                        if not content_range.startswith(f"bytes {offset}-") or not content_range.endswith("/" + str(size)):
                            raise SPXError("服务器返回的续传范围不一致，请重试。")
                    elif response.status_code == 200:
                        offset = 0
                    else:
                        raise SPXError("服务器没有返回完整下载内容。")
                    count = offset
                    with part.open("ab" if offset else "wb") as stream:
                        for data in response.iter_bytes(256 * 1024):
                            if cancel and cancel.is_set():
                                raise DownloadPaused("下载已暂停，重新点击安装即可续传。")
                            if count + len(data) > size:
                                raise SPXError("下载内容超过预期大小。")
                            stream.write(data)
                            count += len(data)
                            now = time.monotonic()
                            if now - last >= .15 or count == size:
                                speed = (count - offset) / max(now - started, .01)
                                progress({"stage": "download", "bytes": count, "total": size, "speed": speed, "eta": (size - count) / speed if speed else None})
                                last = now
                    if count != size:
                        raise httpx.ReadError("incomplete response")
            break
        except DownloadPaused:
            raise
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            if cancel and cancel.is_set():
                raise DownloadPaused("下载已暂停。") from error
            if attempt == 3 or isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500 and error.response.status_code != 429:
                raise SPXError(str(network_error(error, "运行环境下载")) + " 已保留下载进度。") from error
            progress({"stage": "retry", "attempt": attempt + 1})
            if cancel:
                cancel.wait(min(2**attempt, 5))
            else:
                time.sleep(min(2**attempt, 5))
    progress({"stage": "verify", "bytes": size, "total": size})
    if not part.exists() or part.stat().st_size != size or digest(part, cancel) != sha256:
        part.unlink(missing_ok=True)
        raise SPXError("文件校验未通过，已清除损坏的下载。请重试。")
    part.replace(target)
    return target
