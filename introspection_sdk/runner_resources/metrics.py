"""`runner.metrics.*` namespace: bounded telemetry aggregation.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. Wraps the closed,
allow-listed ``POST /v1/metrics`` contract (see the DP
``docs/design/metrics-api.md``): one bounded, read-only aggregation over a
telemetry view. Not a list read — there is no cursor and no Arrow variant;
the request carries an explicit ``from_timestamp`` / ``to_timestamp`` window
and the response is a single :class:`MetricQueryResponse`.
"""

from __future__ import annotations

from typing import Any

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.schemas.metrics import (
    MetricQueryRequest,
    MetricQueryResponse,
)


class Metrics:
    """Read-only Metrics API (``POST /v1/metrics``)."""

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def query(
        self, request: MetricQueryRequest | dict[str, Any]
    ) -> MetricQueryResponse:
        """Execute one bounded metrics query.

        ``request`` is a :class:`MetricQueryRequest` (or an equivalent dict).
        The whole grammar is validated by the DP; passing a typed
        ``MetricQueryRequest`` also validates the closed contract locally
        before the request is sent.
        """
        body = (
            request.model_dump(mode="json", exclude_none=True)
            if isinstance(request, MetricQueryRequest)
            else request
        )
        payload = self._http.request("POST", "/v1/metrics", json=body)
        return MetricQueryResponse.model_validate(payload)


class AsyncMetrics:
    """Async twin of :class:`Metrics` (``POST /v1/metrics``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    async def query(
        self, request: MetricQueryRequest | dict[str, Any]
    ) -> MetricQueryResponse:
        """Execute one bounded metrics query. See :meth:`Metrics.query`."""
        body = (
            request.model_dump(mode="json", exclude_none=True)
            if isinstance(request, MetricQueryRequest)
            else request
        )
        payload = await self._http.request("POST", "/v1/metrics", json=body)
        return MetricQueryResponse.model_validate(payload)
