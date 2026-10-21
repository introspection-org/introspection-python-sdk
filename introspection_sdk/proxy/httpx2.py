"""Native :mod:`httpx2` transports for Introspection egress."""

from __future__ import annotations

from introspection_sdk._async.proxy.httpx2 import (
    AsyncIntrospectionTransport,
)
from introspection_sdk._sync.proxy.httpx2 import (
    IntrospectionTransport,
)

__all__ = ["AsyncIntrospectionTransport", "IntrospectionTransport"]
