"""Code shared by the sync and async twins in :mod:`introspection_sdk.proxy._transport`."""

from __future__ import annotations

from typing import Any

from introspection_sdk.proxy._config import ProxyConfig


def forward_proxy(http: Any, url: str, ssl_context: Any) -> Any:
    """Build a forward proxy whose own TLS trusts the same roots."""

    if http.URL(url).scheme == "https":
        return http.Proxy(url, ssl_context=ssl_context)
    return http.Proxy(url)


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


def unique_transports(*transports: Any | None) -> list[Any]:
    return list(
        {
            id(transport): transport
            for transport in transports
            if transport is not None
        }.values()
    )
