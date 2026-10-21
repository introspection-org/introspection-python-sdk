"""Code shared by the sync and async twins in :mod:`introspection_sdk._http`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


#: Default automatic retries for unary REST calls: ``429`` on every method,
#: ``502``/``503``/``504`` on ``GET`` only (see
#: :func:`introspection_sdk._backoff._is_retryable_status`). ``Retry-After``
#: is honoured as a backoff floor when present. ``0`` disables retrying.
#: Streaming has its own resume budget (see
#: :mod:`introspection_sdk.resumable`).
DEFAULT_MAX_RETRIES = 2


#: Default base step (seconds) of the capped-exponential retry backoff.
DEFAULT_RETRY_BASE = 0.5


@dataclass(frozen=True)
class RawResponse:
    """A raw response body plus headers, returned by ``request(expect="raw")``.

    Used by the Arrow list-read path, where the row values arrive in the
    columnar body and pagination metadata (``X-Next-Cursor`` /
    ``X-Result-Count`` / ``X-Truncated`` / ``X-Total-Count``) moves to
    response headers. Keeps ``httpx`` off the resource layer's surface.
    """

    content: bytes
    headers: Mapping[str, str]


def _clean_params(
    params: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if params is None:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        out[k] = _param_value(v)
    return out


def _param_value(value: Any) -> Any:
    """Render one query-parameter value the way the API expects it.

    ``httpx`` falls back to ``str()`` for anything it does not know, and
    ``str(datetime)`` is the space-separated form ``2025-01-01 12:30:00+00:00``
    -- not ISO-8601. The window parameters (``start`` / ``end`` /
    ``start_date`` / ``end_date``, and the ``start_date`` a ``lookback``
    resolves to) accept ``datetime`` by design, so every one of them went out
    malformed. ``isoformat()`` puts the ``T`` back.
    """
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_param_value(item) for item in value]
    return value
