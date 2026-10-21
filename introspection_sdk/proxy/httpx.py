"""Legacy :mod:`httpx` transports for Harbor and vendor SDK compatibility."""

from __future__ import annotations

from introspection_sdk._async.proxy.httpx import (
    AsyncIntrospectionTransport,
)
from introspection_sdk._sync.proxy.httpx import (
    IntrospectionTransport,
)

__all__ = ["AsyncIntrospectionTransport", "IntrospectionTransport"]
