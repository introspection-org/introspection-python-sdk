"""Tests for the introspection.init() entry point and module proxies."""

from __future__ import annotations

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

import introspection_sdk.otel as introspection
from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel import _reset_for_tests
from introspection_sdk.testing import TestSpanExporter


def setup_function():
    _reset_for_tests()


def _advanced():
    # Both exporters must be in-memory. init() always builds an
    # IntrospectionLogs, so leaving log_exporter unset points the logs stream
    # at the production OTLP endpoint and the atexit flush ships whatever
    # these tests tracked.
    return AdvancedOptions(
        span_exporter=TestSpanExporter(),
        log_exporter=InMemoryLogRecordExporter(),
    )


def test_init_is_idempotent():
    p1 = introspection.init(token="t", advanced=_advanced())
    p2 = introspection.init(token="t")
    assert p1 is p2


def test_proxies_require_init():
    _reset_for_tests()
    with pytest.raises(RuntimeError):
        introspection.track("evt")


def test_track_after_init_does_not_raise():
    introspection.init(token="t", advanced=_advanced())
    introspection.track("evt", {"k": "v"})


def test_advanced_base_url_reaches_the_logs_stream():
    """A caller who configures only `advanced` must not leak to production.

    init() folds the `base_url` parameter into the advanced options for the
    span side; the logs side has to read the same resolved value, or a
    self-hosted deployment ships its track/feedback/identify events to the
    default endpoint.
    """
    introspection.init(
        token="t",
        advanced=AdvancedOptions(
            base_url="http://collector.internal:4318",
            span_exporter=TestSpanExporter(),
            log_exporter=InMemoryLogRecordExporter(),
        ),
    )
    assert (
        introspection.get_client()._base_otel_url
        == "http://collector.internal:4318"
    )


def test_shutdown_clears_state_so_init_rebuilds():
    """The private atexit hook leaves the shut-down provider in place.

    Public shutdown() clears it, so the accessors fail loudly instead of
    handing back dead telemetry, and a later init() reconfigures rather
    than short-circuiting on the stale state.
    """
    introspection.init(token="t", advanced=_advanced())
    introspection.shutdown()
    with pytest.raises(RuntimeError):
        introspection.get_tracer_provider()
    with pytest.raises(RuntimeError):
        introspection.get_client()

    introspection.init(token="t", advanced=_advanced())
    assert introspection.get_tracer_provider() is not None
    assert introspection.get_client() is not None


def test_reinit_after_shutdown_exports_to_the_new_exporter():
    """The attached-marker used to outlive the processor it described.

    A second init() then found the same global provider, short-circuited on
    the stale marker, and exported nothing at all -- silently ignoring the
    new span_exporter it was handed.
    """
    from opentelemetry import trace

    first = TestSpanExporter()
    introspection.init(
        token="t",
        advanced=AdvancedOptions(
            span_exporter=first, log_exporter=InMemoryLogRecordExporter()
        ),
    )
    introspection.shutdown()

    second = TestSpanExporter()
    introspection.init(
        token="t",
        advanced=AdvancedOptions(
            span_exporter=second, log_exporter=InMemoryLogRecordExporter()
        ),
    )
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("chat") as span:
        span.set_attribute("gen_ai.request.model", "claude")
    introspection.get_tracer_provider().force_flush()

    assert [s["name"] for s in second.get_finished_spans()] == ["chat"]
    assert first.get_finished_spans() == []
