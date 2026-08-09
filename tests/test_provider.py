"""Tests for the shared get-or-create TracerProvider core."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from testing import TestSpanExporter

import introspection_sdk.otel as introspection
from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel._provider import (
    _SENTINEL_ATTR,
    _attach_exporter,
    _get_or_create_tracer_provider,
)


@pytest.fixture(autouse=True)
def _reset_global_tracer_provider(monkeypatch):
    """Isolate these tests from any globally-registered TracerProvider.

    ``_get_or_create_tracer_provider`` returns the process-global provider
    when one is already registered, and OTel refuses to replace one. Without
    a reset, whichever suite registered first would win and the get-or-create
    path under test would never run.
    """
    monkeypatch.setattr(
        trace,
        "_TRACER_PROVIDER_SET_ONCE",
        trace._TRACER_PROVIDER_SET_ONCE.__class__(),
    )
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)
    yield


def _processor_count(provider: TracerProvider) -> int:
    return len(provider._active_span_processor._span_processors)


def test_explicit_provider_returned_as_is():
    explicit = TracerProvider()
    out = _get_or_create_tracer_provider(
        token=None,
        explicit_provider=explicit,
        advanced=AdvancedOptions(),
        service_name="svc",
    )
    assert out is explicit


def test_creates_provider_and_marks_sentinel():
    out = _get_or_create_tracer_provider(
        token="t",
        explicit_provider=None,
        advanced=AdvancedOptions(span_exporter=TestSpanExporter()),
        service_name="svc",
    )
    assert isinstance(out, TracerProvider)
    assert getattr(out, _SENTINEL_ATTR, False) is True


def test_attach_is_idempotent():
    provider = TracerProvider()
    advanced = AdvancedOptions(span_exporter=TestSpanExporter())
    _attach_exporter(provider, "t", advanced)
    after_first = _processor_count(provider)
    _attach_exporter(provider, "t", advanced)  # second call must no-op
    assert _processor_count(provider) == after_first


def test_no_token_no_exporter_attached(monkeypatch):
    # No token (env cleared) and no custom exporter -> nothing attached.
    monkeypatch.delenv("INTROSPECTION_TOKEN", raising=False)
    provider = TracerProvider()
    _attach_exporter(provider, None, AdvancedOptions())
    assert getattr(provider, _SENTINEL_ATTR, False) is False
    assert _processor_count(provider) == 0


def test_attached_pipeline_enriches_conversation_id():
    # init()'s pipeline must stamp the active conversation id onto spans,
    # including native (already-gen_ai) spans like Gemini/Anthropic.
    exporter = TestSpanExporter()
    provider = TracerProvider()
    _attach_exporter(provider, "t", AdvancedOptions(span_exporter=exporter))

    tracer = provider.get_tracer("native-instrumentor")
    with introspection.conversation("conv_xyz"):
        with tracer.start_as_current_span("chat") as span:
            span.set_attribute("gen_ai.provider.name", "gemini")

    provider.force_flush()
    spans = exporter.get_finished_spans()
    assert any(
        s["attributes"].get("gen_ai.conversation.id") == "conv_xyz"
        for s in spans
    )
