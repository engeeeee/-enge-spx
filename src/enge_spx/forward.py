"""Connect an owned gateway to the user's loopback line proxy without LAN access."""
import asyncio
import contextlib
import importlib.util
import os
import struct
import sys
import time

from .engine import Engine, HIDDEN, RESOURCES
from .state import Store, fingerprint


def tunnel_type():
    spec = importlib.util.spec_from_file_location("spx_tunnel", RESOURCES / "tunnel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Tunnel


async def run(store):
    engine = Engine(store)
    state = store.read("runtime.json", {})
    target = state.get("forward_target")
    if not target or state.get("phase") not in ("checking", "review", "ready"):
        return
    gateway = engine.inspect("gateway")
    if not gateway or gateway["Id"] != state.get("gateway") or not gateway["State"]["Running"]:
        return
    reader, writer = await asyncio.wait_for(asyncio.open_connection(target["host"], target["port"]), 5)
    writer.close()
    await writer.wait_closed()
    guest_log = (store.home / "forward-guest.log").open("ab")
    process = await asyncio.create_subprocess_exec(*engine.docker.command("exec", "-i", gateway["Id"], "python3", engine.runtime_path("gateway", "tunnel.py")), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=guest_log, env=engine.docker.environment(), creationflags=HIDDEN)
    tunnel = tunnel_type()(process.stdout, process.stdin, (target["host"], target["port"]))
    transfer = asyncio.create_task(tunnel.run())
    try:
        while not transfer.done():
            current = store.read("runtime.json", {})
            if current.get("phase") not in ("checking", "review", "ready") or current.get("gateway") != gateway["Id"] or current.get("policy") != state.get("policy"):
                break
            store.write("forward.json", {"gateway": gateway["Id"], "policy": state["policy"], "heartbeat": time.time(), "pid": os.getpid()})
            await asyncio.sleep(1)
    finally:
        transfer.cancel()
        await asyncio.gather(transfer, return_exceptions=True)
        if process.returncode is None:
            process.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), 5)
            if process.returncode is None:
                process.kill()
                await process.wait()
        guest_log.close()


def main(store):
    with store.lock("forward"):
        asyncio.run(run(store))
