"""HTTP-library-neutral transport routing implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from introspection_sdk.proxy._config import ProxyConfig


def egress_request(
    http: Any,
    request: Any,
    egress_url: str,
    relay_target: str | None = None,
) -> Any:
    """Rebuild a request for egress while retaining its upstream authority."""

    egress = http.URL(egress_url)
    target = request.url.copy_with(
        scheme=egress.scheme,
        host=egress.host,
        port=egress.port,
    )
    headers = request.headers.copy()
    original_authority = request.url.netloc.decode("ascii")
    if relay_target:
        headers["Host"] = egress.netloc.decode("ascii")
        headers["x-introspection-egress-host"] = original_authority
        headers["x-introspection-relay-target"] = relay_target
    else:
        headers["Host"] = original_authority
    return http.Request(
        request.method,
        target,
        headers=headers,
        stream=request.stream,
        extensions=request.extensions,
    )


def select_transport(
    config: ProxyConfig,
    request: Any,
    *,
    direct: Any,
    egress: Any,
    forward: Any | None,
) -> tuple[Any, bool]:
    """Return the transport and whether the request needs egress rewriting."""

    host = request.url.host
    if config.uses_egress(host):
        return egress, True
    if forward is not None and not config.bypasses_forward_proxy(
        host, request.url.port
    ):
        return forward, False
    return direct, False


def handle_request(
    http: Any,
    config: ProxyConfig,
    request: Any,
    *,
    direct: Any,
    egress: Any,
    forward: Any | None,
    send: Callable[[Any, Any], Any],
) -> Any:
    transport, rewrite = select_transport(
        config,
        request,
        direct=direct,
        egress=egress,
        forward=forward,
    )
    if rewrite:
        assert config.egress_url is not None
        request = egress_request(
            http, request, config.egress_url, config.relay_target
        )
    return send(transport, request)


async def handle_async_request(
    http: Any,
    config: ProxyConfig,
    request: Any,
    *,
    direct: Any,
    egress: Any,
    forward: Any | None,
    send: Callable[[Any, Any], Awaitable[Any]],
) -> Any:
    transport, rewrite = select_transport(
        config,
        request,
        direct=direct,
        egress=egress,
        forward=forward,
    )
    if rewrite:
        assert config.egress_url is not None
        request = egress_request(
            http, request, config.egress_url, config.relay_target
        )
    return await send(transport, request)


def unique_transports(*transports: Any | None) -> list[Any]:
    return list(
        {
            id(transport): transport
            for transport in transports
            if transport is not None
        }.values()
    )
