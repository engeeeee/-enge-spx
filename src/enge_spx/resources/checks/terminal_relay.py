"""Owned Linux PTY behind docker exec -i; stdin is bounded D/R/C frames.

No shell interpolation, new mounts, network listeners or elevated privileges.
Keep Windows console parsing out of the application's native VT handshake.
"""
import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

HEADER = struct.Struct("!cI")
LIMIT = 65536


def resize(fd, columns, rows):
    if not 2 <= columns <= 1000 or not 2 <= rows <= 1000:
        raise ValueError("Invalid grid")
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def cleanup(child, master, status):
    groups = {child}
    if master >= 0:
        try:
            foreground = os.tcgetpgrp(master)
            if foreground > 0 and os.getsid(foreground) == child:
                groups.add(foreground)
        except OSError:
            pass
        os.close(master)
    if status is not None:
        return
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
        for group in groups:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + .2
        while time.monotonic() < deadline:
            exited, _ = os.waitpid(child, os.WNOHANG)
            if exited:
                return
            time.sleep(.01)
    os.waitpid(child, 0)


def main():
    columns, rows = map(int, sys.argv[1:3])
    arguments = sys.argv[3:]
    if not arguments or not 2 <= columns <= 1000 or not 2 <= rows <= 1000:
        return 2
    master, slave = pty.openpty()
    ready_read, ready_write = os.pipe()
    try:
        resize(slave, columns, rows)
        child = os.fork()
    except BaseException:
        os.close(master)
        os.close(slave)
        os.close(ready_read)
        os.close(ready_write)
        raise
    if child == 0:
        try:
            os.close(ready_read)
            os.close(master)
            os.login_tty(slave)
            os.write(ready_write, b'1')
            os.close(ready_write)
            os.execvp(arguments[0], arguments)
        except Exception:
            os.write(2, b"ENGE SPX: terminal command failed.\r\n")
            os._exit(126)
    os.close(slave)
    os.close(ready_write)
    try:
        attached = select.select([ready_read], [], [], 2)[0] and os.read(ready_read, 1) == b'1'
    finally:
        os.close(ready_read)
    if not attached:
        cleanup(child, master, None)
        return 2
    status = None
    incoming, pending, output = bytearray(), bytearray(), bytearray()
    closing = False
    try:
        for fd in (0, 1, master):
            os.set_blocking(fd, False)
        while not closing:
            if status is None:
                exited, result = os.waitpid(child, os.WNOHANG)
                if exited:
                    status = result
            readable = ([0] if len(incoming) < LIMIT + HEADER.size and len(pending) < LIMIT else [])
            if master >= 0 and len(output) < LIMIT:
                readable.append(master)
            writable = ([master] if pending and master >= 0 else []) + ([1] if output else [])
            if master < 0 and not output:
                break
            ready_read, ready_write, _ = select.select(readable, writable, [], .25)
            if 0 in ready_read:
                block = os.read(0, 16384)
                if not block:
                    break
                incoming.extend(block)
            while len(incoming) >= HEADER.size and len(pending) < LIMIT:
                kind, size = HEADER.unpack_from(incoming)
                if size > LIMIT or kind not in (b"D", b"R", b"C") or (kind == b"R" and size != 4) or (kind == b"C" and size):
                    raise ValueError("Invalid terminal frame")
                if len(incoming) < HEADER.size + size:
                    break
                data = bytes(incoming[HEADER.size:HEADER.size + size])
                del incoming[:HEADER.size + size]
                if kind == b"D":
                    pending.extend(data)
                elif kind == b"R":
                    if master >= 0:
                        resize(master, *struct.unpack("!HH", data))
                else:
                    closing = True
                    break
            if master in ready_read:
                try:
                    block = os.read(master, 16384)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    block = b""
                if block:
                    output.extend(block)
                else:
                    os.close(master)
                    master = -1
                    pending.clear()
            if master in ready_write and pending:
                try:
                    del pending[:os.write(master, pending)]
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    closing = True
            if 1 in ready_write and output:
                del output[:os.write(1, output)]
        return os.waitstatus_to_exitcode(status) if status is not None else 0
    except (OSError, ValueError):
        return 2
    finally:
        # Only this forked session; never Desktop, other execs or the container.
        cleanup(child, master, status)


if __name__ == "__main__":
    result = main()
    sys.exit(result if result is not None and result >= 0 else 1)
