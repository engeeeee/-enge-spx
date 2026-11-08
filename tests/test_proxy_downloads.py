import hashlib
import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx

from enge_spx.downloads import download, DownloadPaused
from enge_spx.nodes import parse_nodes, uri_node
from enge_spx.proxy import relay_config, proxy_url, protocol, validate_relay
from enge_spx.state import SPXError


class ProxyImportTests(unittest.TestCase):
    def test_socks5_auth_and_escaping(self):
        value = uri_node("socks5://u%40mail:p%3Aa%40ss@198.51.100.3:1080#Landing")
        self.assertEqual(value["outbound"]["username"], "u@mail")
        self.assertEqual(value["outbound"]["password"], "p:a@ss")
        self.assertEqual(value["outbound"]["version"], "5")
        self.assertEqual(protocol(value), "SOCKS5")

    def test_http_and_https_are_distinct(self):
        plain = uri_node("http://proxy.example:8080")
        secure = uri_node("https://user:password@proxy.example:8443")
        self.assertNotIn("tls", plain["outbound"])
        self.assertTrue(secure["outbound"]["tls"]["enabled"])
        self.assertEqual(secure["outbound"]["tls"]["server_name"], "proxy.example")
        self.assertNotIn("network", secure["outbound"])

    def test_https_proxy_is_parsed_without_fetching_subscription(self):
        with patch("urllib.request.build_opener", side_effect=AssertionError("Unexpected fetch")):
            nodes, _ = parse_nodes("https://u:password@proxy.example:443")
        self.assertEqual(protocol(nodes[0]), "HTTPS")

    def test_ports_and_local_ipv6(self):
        self.assertEqual(uri_node("socks5h://localhost")["outbound"]["server_port"], 1080)
        config = relay_config(True, "socks5://u:p%40ss@[::1]:1080")
        self.assertIn("[::1]:1080", proxy_url(config))
        self.assertEqual(validate_relay(config), config)

    def test_host_relay_remains_loopback(self):
        for url in ("http://proxy.example:8080", "http://192.168.1.1:7890", "trojan://secret@localhost:443"):
            with self.subTest(url=url), self.assertRaises(SPXError):
                relay_config(True, url)

    def test_proxy_paths_are_not_mistaken_for_proxy_addresses(self):
        with self.assertRaises(ValueError):
            uri_node("https://example.com/subscription/token")

    def test_clash_proxy_auth_and_tls_are_preserved(self):
        nodes, errors = parse_nodes('''proxies:
  - {name: Socks, type: socks5, server: proxy.example, port: 1080, username: user, password: secret}
  - {name: Secure, type: http, server: proxy.example, port: 8443, username: user, password: secret, tls: true}
  - {name: HTTPS, type: https, server: proxy.example, port: 443}
''')
        self.assertEqual(errors, [])
        self.assertEqual([protocol(n) for n in nodes], ["SOCKS5", "HTTPS", "HTTPS"])
        self.assertEqual(nodes[0]["outbound"]["username"], "user")
        self.assertEqual(nodes[1]["outbound"]["password"], "secret")

    def test_unsupported_socks_tls_is_rejected(self):
        with self.assertRaises(SPXError):
            parse_nodes('proxies: [{type: socks5, server: proxy.example, port: 1080, tls: true}]')


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runtime.gz"
        self.data = bytes(range(256)) * 4096
        self.sha = hashlib.sha256(self.data).hexdigest()

    def server(self, ignore_range=False, corrupt=False):
        self.offsets = []
        def handle(request):
            value = request.headers.get("Range", "bytes=0-")
            offset = int(value[6:-1])
            self.offsets.append(offset)
            if ignore_range:
                offset = 0
            data = self.data[offset:]
            if corrupt:
                data = b"x" * len(data)
            return httpx.Response(206 if offset else 200, content=data, headers={"Content-Range": f"bytes {offset}-{len(self.data)-1}/{len(self.data)}"})
        return httpx.MockTransport(handle)

    def test_pause_then_resume_with_range_and_verified_digest(self):
        cancel = threading.Event()
        def progress(value):
            if value.get("bytes", 0) >= 262144:
                cancel.set()
        with self.assertRaises(DownloadPaused):
            download("https://example.com/runtime", self.path, self.sha, len(self.data), progress, cancel, transport=self.server())
        partial = self.path.with_suffix(".gz.part")
        offset = partial.stat().st_size
        self.assertGreater(offset, 0)
        self.assertLess(offset, len(self.data))
        transport = self.server()
        download("https://example.com/runtime", self.path, self.sha, len(self.data), transport=transport)
        self.assertEqual(self.offsets[0], offset)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_server_ignoring_range_restarts_cleanly(self):
        self.path.with_suffix(".gz.part").write_bytes(self.data[:200])
        download("https://example.com/runtime", self.path, self.sha, len(self.data), transport=self.server(ignore_range=True))
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_corruption_is_rejected_and_partial_removed(self):
        with self.assertRaises(SPXError):
            download("https://example.com/runtime", self.path, self.sha, len(self.data), transport=self.server(corrupt=True))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_suffix(".gz.part").exists())

    def test_completed_cache_does_not_download(self):
        self.path.write_bytes(self.data)
        transport = httpx.MockTransport(lambda r: self.fail("Unexpected network request"))
        download("https://example.com/runtime", self.path, self.sha, len(self.data), transport=transport)


class TunnelTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_large_streams_and_half_close(self):
        from enge_spx.forward import tunnel_type
        tunnel = tunnel_type()
        tasks = []
        async def echo(reader, writer):
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
            writer.close()
        backend = await asyncio.start_server(echo, "127.0.0.1", 0)
        async def host(reader, writer):
            task = asyncio.create_task(tunnel(reader, writer, ("127.0.0.1", backend.sockets[0].getsockname()[1])).run())
            tasks.append(task)
            try:
                await task
            finally:
                writer.close()
                await writer.wait_closed()
        channel = await asyncio.start_server(host, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection("127.0.0.1", channel.sockets[0].getsockname()[1])
        guest = tunnel(reader, writer)
        tasks.append(asyncio.create_task(guest.run()))
        listener = await asyncio.start_server(guest.accept, "127.0.0.1", 0)
        async def exchange():
            reader, writer = await asyncio.open_connection("127.0.0.1", listener.sockets[0].getsockname()[1])
            payload = bytes(range(256)) * 4096
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            self.assertEqual(await reader.read(), payload)
            writer.close()
        try:
            await asyncio.wait_for(asyncio.gather(*(exchange() for _ in range(4))), 15)
        finally:
            writer.close()
            for server in (listener, channel, backend):
                server.close()
                await server.wait_closed()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
