"""Small HTTP clients used by the REST API namespaces.

:class:`_HttpClient` wraps ``httpx.Client`` and :class:`_AsyncHttpClient`
wraps ``httpx.AsyncClient``; both centralise base-URL joining,
``Authorization`` header injection, error translation, and SSE
streaming. Kept private so the public surface stays the REST namespace
classes themselves.

``httpx`` throughout this package is ``httpx2`` under an alias --- the
Pydantic-maintained successor, which the OpenAI, Anthropic and MCP SDKs are
also built on. Callers passing their own ``transport=`` must pass an httpx2
one; see docs/advanced.md. The two clients are kept deliberately symmetric so
the sync and async resource namespaces can mirror each other line for
line.
"""

from __future__ import annotations

from introspection_sdk._async._http import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE,
)
from introspection_sdk._async._http import _AsyncHttpClient as _AsyncHttpClient
from introspection_sdk._async._http import (
    _clean_params as _clean_params,
)
from introspection_sdk._http_common import (
    RawResponse,
)
from introspection_sdk._sync._http import _HttpClient as _HttpClient

__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_BASE",
    "RawResponse",
]
