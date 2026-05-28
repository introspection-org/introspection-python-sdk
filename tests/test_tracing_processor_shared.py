"""Shared-provider mode for IntrospectionTracingProcessor."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider

pytest.importorskip("agents")

from introspection_sdk.otel.processors.tracing_processor import (  # noqa: E402
    IntrospectionTracingProcessor,
)


def test_uses_passed_provider_without_building_exporter():
    provider = TracerProvider()
    proc = IntrospectionTracingProcessor(tracer_provider=provider)
    assert proc._tracer_provider is provider
    assert proc._owns_provider is False


def test_lifecycle_is_noop_in_shared_mode():
    proc = IntrospectionTracingProcessor(tracer_provider=TracerProvider())
    # Caller owns the provider; these must not raise or shut anything down.
    proc.force_flush()
    proc.shutdown()
