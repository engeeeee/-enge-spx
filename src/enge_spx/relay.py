"""Authenticated, loopback-only noVNC display using docker exec stdio."""
import asyncio
import hmac
import json
import mimetypes
from pathlib import Path
import secrets
import subprocess
import urllib.parse

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from .engine import Engine, HIDDEN
from .state import Store


async def run(store: Store):
    engine = Engine(store)
    state = store.read("runtime.json", {})
    if state.get("phase") != "ready":
        return
    browser = engine.inspect("browser")
    if not browser or not browser["State"]["Running"]:
        return
    browser_id, token = browser["Id"], state["browser_token"]
    assets = (store.home / "viewer-assets").resolve()
    control = secrets.token_hex(32)
    origin = ""
    clients = set()

    def response(status, body=b"", content_type="text/plain; charset=utf-8"):
        headers = Headers({"Content-Type": content_type, "Content-Length": str(len(body)), "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return Response(status, "OK" if status == 200 else "Rejected", headers, body)

    async def request(connection, req):
        if req.headers.get("Host", "") != urllib.parse.urlsplit(origin).netloc:
            return response(403)
        if req.path == "/control/status":
            if not hmac.compare_digest(req.headers.get("X-SPX-Control", ""), control):
                return response(403)
            return response(200, json.dumps({"ok": True, "browser": browser_id}).encode(), "application/json")
        if req.headers.get("Upgrade", "").lower() == "websocket":
            target = urllib.parse.urlsplit(req.path)
            candidate = urllib.parse.parse_qs(target.query).get("token", [""])[0]
            if target.path != "/websockify" or req.headers.get("Origin") != origin or not hmac.compare_digest(candidate, token):
                return response(403)
            return None
        try:
            target = urllib.parse.unquote(urllib.parse.urlsplit(req.path).path)
            path = (assets / target.lstrip("/")).resolve()
            if assets not in path.parents or not path.is_file():
                return response(404)
            if path.stat().st_size > 10 * 1024 * 1024:
                return response(413)
            content_type = "text/javascript" if path.suffix == ".js" else mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            return response(200, path.read_bytes(), content_type)
        except (OSError, ValueError):
            return response(404)

    async def handler(websocket):
        if len(clients) >= 4:
            await websocket.close(1013, "Four display connections are already open")
            return
        clients.add(websocket)
        process = None
        tasks = []
        try:
            process = await asyncio.create_subprocess_exec(*engine.docker.command("exec", "-i", "--user", "1000:1000", browser_id, "python3", engine.runtime_path("browser", "vnc_stdio.py")), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=engine.docker.environment(), creationflags=HIDDEN)
            async def upload():
                async for data in websocket:
                    if not isinstance(data, bytes):
                        break
                    process.stdin.write(data)
                    await process.stdin.drain()
            async def download():
                while data := await process.stdout.read(65536):
                    await websocket.send(data)
            tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (OSError, ConnectionClosed):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            clients.discard(websocket)
            await websocket.close()

    async with serve(handler, "127.0.0.1", 0, process_request=request, compression=None, ping_timeout=60, max_size=2 * 1024 * 1024, subprotocols=["binary"], select_subprotocol=lambda conn, protocols: "binary" if "binary" in protocols else None) as server:
        port = server.sockets[0].getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        current = store.read("runtime.json", {})
        if current.get("phase") != "ready" or current.get("browser_token") != token:
            return
        store.write("relay.json", {"origin": origin, "control": control, "browser": browser_id, "token": token})
        try:
            while True:
                current = store.read("runtime.json", {})
                if current.get("phase") != "ready" or current.get("browser_token") != token:
                    break
                await asyncio.sleep(2)
        finally:
            if store.read("relay.json", {}).get("control") == control:
                (store.home / "relay.json").unlink(missing_ok=True)


def main(store):
    with store.lock("relay"):
        asyncio.run(run(store))
