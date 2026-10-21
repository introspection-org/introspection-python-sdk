"""REST-only Introspection client.

This module exposes the CP REST surface
(:class:`~introspection_sdk.resources.Runtimes`,
:class:`~introspection_sdk.resources.Experiments`) plus the DP
:class:`~introspection_sdk.runner.Runner` flow, **without** importing
OpenTelemetry.

For OpenTelemetry-based emission of ``track`` / ``feedback`` /
``identify`` events, install the ``[otel]`` extra and use
:class:`introspection_sdk.IntrospectionLogs`. For trace export, attach
:class:`introspection_sdk.IntrospectionSpanProcessor` to your
``TracerProvider`` — or call :func:`introspection_sdk.otel.init` to get
both surfaces at once.
"""

from __future__ import annotations

from introspection_sdk._async.client import (
    AsyncIntrospectionClient,
)
from introspection_sdk._sync.client import (
    IntrospectionClient,
)

__all__ = ["AsyncIntrospectionClient", "IntrospectionClient"]
