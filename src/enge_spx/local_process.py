"""Bounded CLI capture without pipes inherited by a Windows CLI plugin.

subprocess.run drains captured PIPEs after killing a timed-out Windows child.
A still-running plugin can keep those pipes open, exhausting a caller's entire
verification budget. Private temporary files need no EOF from descendants.
Only the subprocess owned by run() is reaped; Desktop/WSL are never killed.
"""
import subprocess
import tempfile


def run(command, *, timeout, env, encoding="utf-8", limit=65536):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(command, stdout=output, stderr=errors,
                                stdin=subprocess.DEVNULL, timeout=timeout, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        captured = []
        for stream in (output, errors):
            stream.seek(0)
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise OSError("Local command output exceeded its verification limit")
            captured.append(data.decode(encoding, errors="replace") if encoding else data)
        return subprocess.CompletedProcess(result.args, result.returncode, *captured)
