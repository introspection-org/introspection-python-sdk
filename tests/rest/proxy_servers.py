"""Loopback CONNECT proxy and HTTPS origin for proxy-native tests."""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import trustme

ORIGIN_HOST = "api.provider.test"
SESSION_LOCATOR = "loc-test-session"
PROXY_AUTHORIZATION = "Basic " + base64.b64encode(
    f"session:{SESSION_LOCATOR}".encode()
).decode("ascii")


@dataclass
class EgressProxy:
    """A CONNECT proxy that answers 407 without the session credential."""

    url: str
    ca_bundle: Path
    connects: list[tuple[str, str | None]] = field(default_factory=list)

    def proxy_url(self, *, credential: bool = True) -> str:
        scheme, _, authority = self.url.partition("://")
        if not credential:
            return self.url
        return f"{scheme}://session:{SESSION_LOCATOR}@{authority}"


async def _read_head(
    reader: asyncio.StreamReader,
) -> tuple[str, dict[str, str]]:
    head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
    request_line, *lines = head.split("\r\n")
    headers = {}
    for line in lines:
        name, _, value = line.partition(":")
        if name:
            headers[name.strip().lower()] = value.strip()
    return request_line, headers


async def _pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, ssl.SSLError):
        pass
    finally:
        writer.close()


async def _serve_origin(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    request_line, headers = await _read_head(reader)
    body = json.dumps(
        {
            "request": request_line,
            "host": headers.get("host"),
            "authorization": headers.get("authorization"),
        }
    ).encode()
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
        + body
    )
    await writer.drain()
    writer.close()


@contextmanager
def egress_proxy(tmp_path: Path, *, tls: bool) -> Iterator[EgressProxy]:
    """Run an HTTPS origin behind a credentialed CONNECT proxy."""

    ca = trustme.CA()
    leaf = ca.issue_cert("localhost", ORIGIN_HOST)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    leaf.configure_cert(server_context)
    ca_bundle = tmp_path / "platform-ca.pem"
    ca.cert_pem.write_to_path(str(ca_bundle))

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    async def start() -> tuple[asyncio.Server, asyncio.Server, EgressProxy]:
        origin = await asyncio.start_server(
            _serve_origin, "127.0.0.1", 0, ssl=server_context
        )
        origin_port = origin.sockets[0].getsockname()[1]
        connects: list[tuple[str, str | None]] = []

        async def serve_proxy(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            request_line, headers = await _read_head(reader)
            method, target, _ = request_line.split(" ", 2)
            credential = headers.get("proxy-authorization")
            connects.append((target, credential))
            if method != "CONNECT" or credential != PROXY_AUTHORIZATION:
                writer.write(
                    b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                    b'Proxy-Authenticate: Basic realm="egress"\r\n'
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
                await writer.drain()
                writer.close()
                return
            if target != f"{ORIGIN_HOST}:443":
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                writer.close()
                return
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", origin_port
            )
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await asyncio.gather(
                _pipe(reader, upstream_writer),
                _pipe(upstream_reader, writer),
            )

        proxy = await asyncio.start_server(
            serve_proxy,
            "127.0.0.1",
            0,
            ssl=server_context if tls else None,
        )
        proxy_port = proxy.sockets[0].getsockname()[1]
        scheme = "https" if tls else "http"
        state = EgressProxy(
            url=f"{scheme}://localhost:{proxy_port}",
            ca_bundle=ca_bundle,
            connects=connects,
        )
        return origin, proxy, state

    origin, proxy, state = asyncio.run_coroutine_threadsafe(
        start(), loop
    ).result(timeout=10)
    try:
        yield state
    finally:

        async def stop() -> None:
            for server in (proxy, origin):
                server.close()

        asyncio.run_coroutine_threadsafe(stop(), loop).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=10)
        loop.close()
