"""Async twins re-exported by :mod:`introspection_sdk.proxy._transport`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from introspection_sdk.proxy._config import ProxyConfig
from introspection_sdk.proxy._transport_common import (
    egress_request,
    select_transport,
)


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
