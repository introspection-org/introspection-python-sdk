"""HTTP-library-neutral transport routing implementation."""

from __future__ import annotations

from introspection_sdk._async.proxy._transport import (
    egress_request,
    forward_proxy,
    handle_async_request,
    select_transport,
    unique_transports,
)
from introspection_sdk._sync.proxy._transport import (
    handle_request,
)

__all__ = [
    "egress_request",
    "forward_proxy",
    "handle_async_request",
    "handle_request",
    "select_transport",
    "unique_transports",
]
