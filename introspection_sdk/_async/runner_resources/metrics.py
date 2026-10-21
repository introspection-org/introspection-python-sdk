"""Re-exported by :mod:`introspection_sdk.runner_resources.metrics`."""

from __future__ import annotations

from typing import Any

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.schemas.metrics import (
    MetricQueryRequest,
    MetricQueryResponse,
)


class AsyncMetrics:
    """Read-only Metrics API (``POST /v1/metrics``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    async def query(
        self, request: MetricQueryRequest | dict[str, Any]
    ) -> MetricQueryResponse:
        # unasync: async-only (the sync twin's docstring follows)
        """Execute one bounded metrics query. See :meth:`Metrics.query`."""
        # unasync: end
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
        payload = await self._http.request("POST", "/v1/metrics", json=body)
        return MetricQueryResponse.model_validate(payload)
