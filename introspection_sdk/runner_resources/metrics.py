"""`runner.metrics.*` namespace: bounded telemetry aggregation.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. Wraps the closed,
allow-listed ``POST /v1/metrics`` contract: one bounded, read-only aggregation over a
telemetry view. Not a list read — there is no cursor and no Arrow variant;
the request carries an explicit ``from_timestamp`` / ``to_timestamp`` window
and the response is a single :class:`MetricQueryResponse`.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.metrics import (
    AsyncMetrics,
)
from introspection_sdk._sync.runner_resources.metrics import (
    Metrics,
)

__all__ = [
    "AsyncMetrics",
    "Metrics",
]
