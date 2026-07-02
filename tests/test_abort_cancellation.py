"""Caller-abort → cancelled span annotation (mirrors the JS SDK).

A user-initiated cancellation of an in-flight LLM call — an ``asyncio`` task
cancel, a Ctrl-C, or breaking out of a stream early — must read as a deliberate
stop, not a failure: the span stays status ``UNSET`` and is annotated with the
native ``gen_ai.response.finish_reasons=["aborted"]`` plus
``introspection.termination_reason="cancelled"``. These tests drive the real
Anthropic/Gemini wrappers and the LangChain callback handler against an
in-memory exporter — no models, no network.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from introspection_sdk import AdvancedOptions
from introspection_sdk.otel import anthropic as anthropic_mod
from introspection_sdk.otel import gemini as gemini_mod
from introspection_sdk.otel._termination import mark_span_cancelled
from introspection_sdk.otel.processors.langchain_callback_handler import (
    IntrospectionCallbackHandler,
)

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


# ---------------------------------------------------------------------------
# Anthropic: non-streaming create
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc", [asyncio.CancelledError(), KeyboardInterrupt()]
)
def test_anthropic_create_cancelled(tracer, exporter, exc):
    with pytest.raises(type(exc)):
        anthropic_mod.traced_messages_create(
            tracer,
            _Client(exc),
            model="claude-x",
            messages=[{"role": "user", "content": "hi"}],
        )
    _assert_cancelled(_only(exporter))


def test_anthropic_create_error_still_errors(tracer, exporter):
    """A real failure is unchanged: ERROR status, no cancel markers."""
    with pytest.raises(ValueError):
        anthropic_mod.traced_messages_create(
            tracer,
            _Client(ValueError("boom")),
            model="claude-x",
            messages=[{"role": "user", "content": "hi"}],
        )
    span = _only(exporter)
    assert span.status.status_code == StatusCode.ERROR
    assert "introspection.termination_reason" not in dict(
        span.attributes or {}
    )


# ---------------------------------------------------------------------------
# Anthropic: streaming (messages.create(stream=True) wrapper)
# ---------------------------------------------------------------------------


def test_anthropic_stream_cancelled_midway(tracer, exporter):
    def _inner():
        yield SimpleNamespace(type="ping")
        raise asyncio.CancelledError()

    span, tok = anthropic_mod._start_span(tracer, "claude-x")
    wrapper = anthropic_mod._StreamWrapper(_inner(), span, tok)
    with pytest.raises(asyncio.CancelledError):
        for _ in wrapper:
            pass
    _assert_cancelled(_only(exporter))


def test_anthropic_stream_normal_completion_sets_ok(tracer, exporter):
    def _inner():
        yield SimpleNamespace(type="ping")

    span, tok = anthropic_mod._start_span(tracer, "claude-x")
    wrapper = anthropic_mod._StreamWrapper(_inner(), span, tok)
    for _ in wrapper:
        pass
    span_out = _only(exporter)
    assert span_out.status.status_code == StatusCode.OK
    assert "introspection.termination_reason" not in dict(
        span_out.attributes or {}
    )


# ---------------------------------------------------------------------------
# Gemini: sync streaming (early break closes the generator → GeneratorExit)
# ---------------------------------------------------------------------------


def test_gemini_sync_stream_early_break_is_cancelled(tracer, exporter):
    def _chunks():
        yield SimpleNamespace()
        yield SimpleNamespace()

    span, tok = gemini_mod._start_span(tracer, "gemini-x")
    wrapper = gemini_mod._SyncStreamWrapper(_chunks(), span, tok)
    for _ in wrapper:
        break  # closes the generator → GeneratorExit at the yield
    _assert_cancelled(_only(exporter))


def test_gemini_sync_stream_normal_completion_sets_ok(tracer, exporter):
    def _chunks():
        yield SimpleNamespace()

    span, tok = gemini_mod._start_span(tracer, "gemini-x")
    wrapper = gemini_mod._SyncStreamWrapper(_chunks(), span, tok)
    list(wrapper)
    assert _only(exporter).status.status_code == StatusCode.OK


# ---------------------------------------------------------------------------
# Gemini: async streaming (task cancel and early aclose)
# ---------------------------------------------------------------------------


async def test_gemini_async_stream_cancelled_midway(tracer, exporter):
    async def _chunks():
        yield SimpleNamespace()
        raise asyncio.CancelledError()

    span, tok = gemini_mod._start_span(tracer, "gemini-x")
    wrapper = gemini_mod._AsyncStreamWrapper(_chunks(), span, tok)
    with pytest.raises(asyncio.CancelledError):
        async for _ in wrapper:
            pass
    _assert_cancelled(_only(exporter))


async def test_gemini_async_stream_early_aclose_is_cancelled(tracer, exporter):
    async def _chunks():
        yield SimpleNamespace()
        yield SimpleNamespace()

    span, tok = gemini_mod._start_span(tracer, "gemini-x")
    wrapper = gemini_mod._AsyncStreamWrapper(_chunks(), span, tok)
    agen = wrapper.__aiter__()
    await agen.__anext__()
    await agen.aclose()  # GeneratorExit into the async generator
    _assert_cancelled(_only(exporter))


# ---------------------------------------------------------------------------
# LangChain callback handler: on_llm_error / on_tool_error / on_chain_error
# ---------------------------------------------------------------------------


@pytest.fixture
def handler(exporter: InMemorySpanExporter) -> IntrospectionCallbackHandler:
    return IntrospectionCallbackHandler(
        advanced=AdvancedOptions(span_exporter=exporter)
    )


def test_langchain_llm_error_cancelled(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_llm_start({}, ["p"], run_id=run_id)
    handler.on_llm_error(asyncio.CancelledError(), run_id=run_id)
    _assert_cancelled(_only(exporter))


def test_langchain_llm_error_real_error_unchanged(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_llm_start({}, ["p"], run_id=run_id)
    handler.on_llm_error(ValueError("boom"), run_id=run_id)
    span = _only(exporter)
    assert span.status.status_code == StatusCode.ERROR
    assert dict(span.attributes or {})["exception.message"] == "boom"
    assert "introspection.termination_reason" not in dict(
        span.attributes or {}
    )


def test_langchain_tool_error_cancelled(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_tool_start({"name": "t"}, "in", run_id=run_id)
    handler.on_tool_error(KeyboardInterrupt(), run_id=run_id)
    _assert_cancelled(_only(exporter))


def test_langchain_chain_error_cancelled(handler, exporter):
    run_id = uuid.uuid4()
    handler.on_chain_start({"name": "c"}, {}, run_id=run_id)
    handler.on_chain_error(asyncio.CancelledError(), run_id=run_id)
    _assert_cancelled(_only(exporter))
