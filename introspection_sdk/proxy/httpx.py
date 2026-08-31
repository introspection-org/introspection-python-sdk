"""Legacy :mod:`httpx` transports for Harbor and vendor SDK compatibility."""

from __future__ import annotations

try:
    import httpx
except ImportError as error:  # pragma: no cover - requires an install variant
    raise ImportError(
        "Install introspection-sdk[proxy-httpx] to use this adapter"
    ) from error

from introspection_sdk.proxy._config import ProxyConfig
from introspection_sdk.proxy._transport import (
    handle_async_request,
    handle_request,
    unique_transports,
)


class IntrospectionTransport(httpx.BaseTransport):
    """Synchronous legacy-``httpx`` endpoint-binding transport."""

    def __init__(
        self,
        config: ProxyConfig | None = None,
        *,
        verify: bool | str = True,
        _direct: httpx.BaseTransport | None = None,
        _egress: httpx.BaseTransport | None = None,
        _forward: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or ProxyConfig.from_env()
        self._direct = _direct or httpx.HTTPTransport(verify=verify)
        self._egress = _egress or httpx.HTTPTransport(verify=verify)
        self._forward = _forward
        if self._forward is None and self.config.forward_proxy_url:
            self._forward = httpx.HTTPTransport(
                verify=verify, proxy=self.config.forward_proxy_url
            )

    @classmethod
    def from_env(cls, *, verify: bool | str = True) -> IntrospectionTransport:
        return cls(ProxyConfig.from_env(), verify=verify)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return handle_request(
            httpx,
            self.config,
            request,
            direct=self._direct,
            egress=self._egress,
            forward=self._forward,
            send=lambda transport, value: transport.handle_request(value),
        )

    def close(self) -> None:
        for transport in unique_transports(
            self._direct, self._egress, self._forward
        ):
            transport.close()


class AsyncIntrospectionTransport(httpx.AsyncBaseTransport):
    """Asynchronous legacy-``httpx`` endpoint-binding transport."""

    def __init__(
        self,
        config: ProxyConfig | None = None,
        *,
        verify: bool | str = True,
        _direct: httpx.AsyncBaseTransport | None = None,
        _egress: httpx.AsyncBaseTransport | None = None,
        _forward: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or ProxyConfig.from_env()
        self._direct = _direct or httpx.AsyncHTTPTransport(verify=verify)
        self._egress = _egress or httpx.AsyncHTTPTransport(verify=verify)
        self._forward = _forward
        if self._forward is None and self.config.forward_proxy_url:
            self._forward = httpx.AsyncHTTPTransport(
                verify=verify, proxy=self.config.forward_proxy_url
            )

    @classmethod
    def from_env(
        cls, *, verify: bool | str = True
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


__all__ = ["AsyncIntrospectionTransport", "IntrospectionTransport"]
