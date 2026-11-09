"""Bounded TCP multiplexing over authenticated docker-exec stdio.

The guest opens only a loopback listener; the host opens only connections to one
configured local proxy. Neither endpoint exposes a listener on the host's LAN.
"""
import asyncio
import contextlib
import struct
import sys

HEADER = struct.Struct("!BII")
OPEN, DATA, CLOSE, EOF, CREDIT = 0, 1, 2, 3, 4
CHUNK = 65536
MAX_STREAMS = 64
WINDOW = 8


class Tunnel:
    def __init__(self, reader, writer, target=None, flow_control=True):
        self.reader, self.writer, self.target = reader, writer, target
        self.flow_control = flow_control
        self.streams = {}
        self.next_id = 1
        self.output_lock = asyncio.Lock()

    def new_stream(self):
        # Each stream owns its receive window. The extra slot is reserved for
        # EOF, so a slow consumer cannot block parsing every other stream.
        return {"queue": asyncio.Queue(maxsize=WINDOW + 1), "credit": asyncio.BoundedSemaphore(WINDOW), "eof": False}

    async def send(self, kind, identity, data=b""):
        async with self.output_lock:
            self.writer.write(HEADER.pack(kind, identity, len(data)) + data)
            await self.writer.drain()

    async def transfer(self, identity, state, reader, writer):
        state["writer"] = writer
        async def upload():
            while True:
                if self.flow_control:
                    await state["credit"].acquire()
                data = await reader.read(CHUNK)
                if not data:
                    break
                await self.send(DATA, identity, data)
            await self.send(EOF, identity)
        async def download():
            while True:
                data = await state["queue"].get()
                if data is None:
                    return
                if data == b"":
                    if writer.can_write_eof():
                        writer.write_eof()
                    return
                writer.write(data)
                await writer.drain()
                if self.flow_control:
                    await self.send(CREDIT, identity)
        tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def host_stream(self, identity, state):
        writer = None
        failed = False
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(*self.target), 10)
            await self.transfer(identity, state, reader, writer)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            failed = True
        finally:
            if writer:
                writer.close()
            self.streams.pop(identity, None)
            if failed:
                with contextlib.suppress(OSError, ConnectionError):
                    await self.send(CLOSE, identity)

    async def accept(self, reader, writer):
        if len(self.streams) >= MAX_STREAMS:
            writer.close()
            return
        identity = self.next_id
        self.next_id = self.next_id % 0xFFFFFFFF + 1
        state = self.new_stream()
        state.update(writer=writer, task=asyncio.current_task())
        self.streams[identity] = state
        failed = False
        try:
            await self.send(OPEN, identity)
            await self.transfer(identity, state, reader, writer)
        except (OSError, asyncio.IncompleteReadError):
            failed = True
        finally:
            self.streams.pop(identity, None)
            writer.close()
            if failed:
                with contextlib.suppress(OSError, ConnectionError):
                    await self.send(CLOSE, identity)

    async def run(self):
        try:
            while True:
                kind, identity, size = HEADER.unpack(await self.reader.readexactly(HEADER.size))
                if size > CHUNK or identity == 0 or kind not in (OPEN, DATA, CLOSE, EOF, CREDIT) or kind != DATA and size or kind == CREDIT and not self.flow_control:
                    raise ValueError("Invalid tunnel frame")
                data = await self.reader.readexactly(size)
                if kind == OPEN:
                    if not self.target or identity in self.streams or len(self.streams) >= MAX_STREAMS:
                        await self.send(CLOSE, identity)
                        continue
                    state = self.new_stream()
                    self.streams[identity] = state
                    state["task"] = asyncio.create_task(self.host_stream(identity, state))
                elif identity in self.streams:
                    state = self.streams[identity]
                    if kind == DATA:
                        if state["eof"] or not data:
                            raise ValueError("Data after EOF or empty data frame")
                        if self.flow_control:
                            state["queue"].put_nowait(data)
                        else:
                            await state["queue"].put(data)
                    elif kind == EOF:
                        if state["eof"]:
                            raise ValueError("Duplicate EOF")
                        state["eof"] = True
                        if self.flow_control:
                            state["queue"].put_nowait(b"")
                        else:
                            await state["queue"].put(b"")
                    elif kind == CREDIT:
                        state["credit"].release()
                    elif kind == CLOSE:
                        state["task"].cancel()
        except asyncio.IncompleteReadError:
            pass
        finally:
            tasks = [state["task"] for state in list(self.streams.values())]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


async def guest():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout.buffer)
    writer = asyncio.StreamWriter(transport, protocol, None, loop)
    tunnel = Tunnel(reader, writer)
    async with await asyncio.start_server(tunnel.accept, "127.0.0.1", 2081):
        await tunnel.run()


if __name__ == "__main__":
    asyncio.run(guest())
