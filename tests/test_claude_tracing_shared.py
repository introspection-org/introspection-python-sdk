"""Shared-provider mode for ClaudeTracingProcessor."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

pytest.importorskip("claude_agent_sdk")

from testing import TestSpanExporter  # noqa: E402

from introspection_sdk.otel.processors.claude_tracing_processor import (  # noqa: E402
    ClaudeTracingProcessor,
)


def _processor_count(provider: TracerProvider) -> int:
    return len(provider._active_span_processor._span_processors)


def test_uses_passed_provider():
    provider = TracerProvider()
    proc = ClaudeTracingProcessor(tracer_provider=provider)
    assert proc._tracer_provider is provider
    assert proc._owns_provider is False


def test_lifecycle_is_noop_in_shared_mode():
    proc = ClaudeTracingProcessor(tracer_provider=TracerProvider())
    proc.force_flush()
    proc.shutdown()


def test_additional_processors_attach_to_shared_provider():
    provider = TracerProvider()
    before = _processor_count(provider)
    ClaudeTracingProcessor(
        tracer_provider=provider,
        additional_span_processors=[SimpleSpanProcessor(TestSpanExporter())],
    )
    assert _processor_count(provider) == before + 1
