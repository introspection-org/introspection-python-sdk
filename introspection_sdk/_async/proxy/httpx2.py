"""Re-exported by :mod:`introspection_sdk.proxy.httpx2`."""

from __future__ import annotations

import ssl

import httpx2 as httpx

from introspection_sdk.proxy._config import ProxyConfig
from introspection_sdk.proxy._transport import (
    forward_proxy,
    handle_async_request,
    unique_transports,
)


class AsyncIntrospectionTransport(httpx.AsyncBaseTransport):
    """Asynchronous ``httpx2`` endpoint-binding transport."""

    def __init__(
        self,
        config: ProxyConfig | None = None,
        *,
        verify: ssl.SSLContext | bool | str = True,
        _direct: httpx.AsyncBaseTransport | None = None,
        _egress: httpx.AsyncBaseTransport | None = None,
        _forward: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or ProxyConfig.from_env()
        ssl_context = httpx.create_ssl_context(verify=verify)
        self._direct = _direct or httpx.AsyncHTTPTransport(verify=ssl_context)
        self._egress = _egress or httpx.AsyncHTTPTransport(verify=ssl_context)
        self._forward = _forward
        if self._forward is None and self.config.forward_proxy_url:
            self._forward = httpx.AsyncHTTPTransport(
                verify=ssl_context,
                proxy=forward_proxy(
                    httpx, self.config.forward_proxy_url, ssl_context
                ),
            )

    @classmethod
    def from_env(
        cls, *, verify: ssl.SSLContext | bool | str = True
    ) -> AsyncIntrospectionTransport:
        return cls(ProxyConfig.from_env(), verify=verify)

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        return await handle_async_request(
            httpx,
            self.config,
            request,
            direct=self._direct,
            egress=self._egress,
            forward=self._forward,
            send=lambda transport, value: transport.handle_async_request(
                value
            ),
        )

    async def aclose(self) -> None:
        for transport in unique_transports(
            self._direct, self._egress, self._forward
        ):
            await transport.aclose()
