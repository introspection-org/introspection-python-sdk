"""Caller-abort → cancelled span annotation (mirrors the JS SDK).

A user-initiated cancellation of an in-flight LLM call — an ``asyncio`` task
cancel, a Ctrl-C, or breaking out of a stream early — must read as a deliberate
stop, not a failure: the span stays status ``UNSET`` and is annotated with the
native ``gen_ai.response.finish_reasons=["aborted"]`` plus
``introspection.termination_reason="cancelled"``. These tests exercise the
shared ``mark_span_cancelled`` helper against an in-memory exporter — no
models, no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from introspection_sdk.otel._termination import mark_span_cancelled

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def tracer(exporter: InMemorySpanExporter):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test-abort")


def _only(exporter: InMemorySpanExporter):
    spans = list(exporter.get_finished_spans())
    assert len(spans) == 1, f"expected one span, got {len(spans)}"
    return spans[0]


def _assert_cancelled(span) -> None:
    """The span reads as a caller-cancel: Unset status + the two markers."""
    attrs = dict(span.attributes or {})
    # OTel stores a list attribute as a tuple.
    assert attrs["gen_ai.response.finish_reasons"] == ("aborted",)
    assert attrs["introspection.termination_reason"] == "cancelled"
    assert span.status.status_code == StatusCode.UNSET
    assert "exception" not in [e.name for e in (span.events or [])]


class _Messages:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def create(self, **kwargs: Any) -> Any:
        raise self._exc


class _Client:
    def __init__(self, exc: BaseException) -> None:
        self.messages = _Messages(exc)


# ---------------------------------------------------------------------------
# Unit: the shared helper
# ---------------------------------------------------------------------------


def test_mark_span_cancelled_sets_markers_and_leaves_status_unset(tracer):
    span = tracer.start_span("chat")
    mark_span_cancelled(span)
    span.end()
    attrs = dict(span.attributes or {})
    assert attrs["gen_ai.response.finish_reasons"] == ("aborted",)
    assert attrs["introspection.termination_reason"] == "cancelled"
    assert span.status.status_code == StatusCode.UNSET


def test_mark_span_cancelled_noop_on_ended_span(tracer):
    span = tracer.start_span("chat")
    span.end()
    # Must not raise on a non-recording span.
    mark_span_cancelled(span)
    assert "introspection.termination_reason" not in dict(
        span.attributes or {}
    )
