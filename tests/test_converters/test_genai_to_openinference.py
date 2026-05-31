"""Tests for the gen_ai-semconv → OpenInference converter.

``convert_genai_to_openinference`` is a pure dict→dict transform.
``OpenInferenceSpanProcessor`` is exercised through a real OTel
``TracerProvider`` and a real capturing downstream processor — no mocks.
"""

from __future__ import annotations

import json

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider

from introspection_sdk.converters.genai_to_openinference import (
    OpenInferenceSpanProcessor,
    convert_genai_to_openinference,
)
from introspection_sdk.types import GenAiSemconv as GenAI
from introspection_sdk.types import OpenInferenceSemconv as OI

# --- convert_genai_to_openinference (pure) --------------------------


def test_empty_and_none_attrs_return_empty():
    assert convert_genai_to_openinference(None) == {}
    assert convert_genai_to_openinference({}) == {}


def test_model_and_token_counts():
    oi = convert_genai_to_openinference(
        {
            GenAI.REQUEST_MODEL: "claude-haiku-4-5",
            GenAI.INPUT_TOKENS: 12,
            GenAI.OUTPUT_TOKENS: 34,
        }
    )
    assert oi[OI.SPAN_KIND] == "LLM"
    assert oi[OI.LLM_MODEL_NAME] == "claude-haiku-4-5"
    assert oi[OI.LLM_TOKEN_COUNT_PROMPT] == 12
    assert oi[OI.LLM_TOKEN_COUNT_COMPLETION] == 34


def test_input_messages_with_text():
    msgs = [{"role": "user", "parts": [{"type": "text", "content": "Hi"}]}]
    oi = convert_genai_to_openinference(
        {GenAI.INPUT_MESSAGES: json.dumps(msgs)}
    )
    assert oi[f"{OI.LLM_INPUT_MESSAGES}.0.message.role"] == "user"
    assert oi[f"{OI.LLM_INPUT_MESSAGES}.0.message.content"] == "Hi"


def test_system_instructions_prepended_as_system_message():
    sys = [{"type": "text", "content": "Be brief"}]
    msgs = [{"role": "user", "parts": [{"type": "text", "content": "Hi"}]}]
    oi = convert_genai_to_openinference(
        {
            GenAI.SYSTEM_INSTRUCTIONS: json.dumps(sys),
            GenAI.INPUT_MESSAGES: json.dumps(msgs),
        }
    )
    assert oi[f"{OI.LLM_INPUT_MESSAGES}.0.message.role"] == "system"
    assert oi[f"{OI.LLM_INPUT_MESSAGES}.0.message.content"] == "Be brief"
    assert oi[f"{OI.LLM_INPUT_MESSAGES}.1.message.role"] == "user"


def test_system_instructions_without_input_messages():
    sys = [{"type": "text", "content": "Be brief"}]
    oi = convert_genai_to_openinference(
        {GenAI.SYSTEM_INSTRUCTIONS: json.dumps(sys)}
    )
    assert oi[f"{OI.LLM_INPUT_MESSAGES}.0.message.role"] == "system"


def test_tool_call_request_is_flattened():
    msgs = [
        {
            "role": "assistant",
            "parts": [
                {
                    "type": "tool_call",
                    "id": "call_1",
                    "name": "get_weather",
                    "arguments": {"city": "SF"},
                }
            ],
        }
    ]
    oi = convert_genai_to_openinference(
        {GenAI.OUTPUT_MESSAGES: json.dumps(msgs)}
    )
    base = f"{OI.LLM_OUTPUT_MESSAGES}.0.message.tool_calls.0.tool_call"
    assert oi[f"{base}.id"] == "call_1"
    assert oi[f"{base}.function.name"] == "get_weather"
    assert json.loads(oi[f"{base}.function.arguments"]) == {"city": "SF"}


def test_tool_response_message_maps_to_tool_role():
    msgs = [
        {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call_response",
                    "id": "call_1",
                    "response": {"temp": 70},
                }
            ],
        }
    ]
    oi = convert_genai_to_openinference(
        {GenAI.INPUT_MESSAGES: json.dumps(msgs)}
    )
    prefix = f"{OI.LLM_INPUT_MESSAGES}.0.message"
    assert oi[f"{prefix}.role"] == "tool"
    assert oi[f"{prefix}.tool_call_id"] == "call_1"
    assert json.loads(oi[f"{prefix}.content"]) == {"temp": 70}


def test_output_message_with_finish_reason():
    msgs = [
        {
            "role": "assistant",
            "parts": [{"type": "text", "content": "Done"}],
            "finish_reason": "stop",
        }
    ]
    oi = convert_genai_to_openinference(
        {GenAI.OUTPUT_MESSAGES: json.dumps(msgs)}
    )
    assert oi[f"{OI.LLM_OUTPUT_MESSAGES}.0.message.content"] == "Done"


def test_invalid_messages_json_is_skipped():
    oi = convert_genai_to_openinference({GenAI.INPUT_MESSAGES: "{not json"})
    # Only the span-kind default survives.
    assert oi == {OI.SPAN_KIND: "LLM"}


def test_non_list_messages_json_is_skipped():
    oi = convert_genai_to_openinference(
        {GenAI.INPUT_MESSAGES: json.dumps({"role": "user"})}
    )
    assert oi == {OI.SPAN_KIND: "LLM"}


def test_invalid_system_instructions_json_is_ignored():
    oi = convert_genai_to_openinference(
        {GenAI.SYSTEM_INSTRUCTIONS: "{not json"}
    )
    assert oi == {OI.SPAN_KIND: "LLM"}


# --- OpenInferenceSpanProcessor (real spans, real downstream) -------


class _CapturingProcessor(SpanProcessor):
    """A real downstream processor that records what it receives."""

    def __init__(self) -> None:
        self.started: list[object] = []
        self.ended: list[ReadableSpan] = []
        self.shutdown_called = False
        self.flushed = False

    def on_start(self, span, parent_context: Context | None = None) -> None:
        self.started.append(span)

    def on_end(self, span: ReadableSpan) -> None:
        self.ended.append(span)

    def shutdown(self) -> None:
        self.shutdown_called = True

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.flushed = True
        return True


def _provider(downstream: _CapturingProcessor) -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(OpenInferenceSpanProcessor(downstream))
    return provider


def test_processor_converts_and_forwards_real_span():
    downstream = _CapturingProcessor()
    tracer = _provider(downstream).get_tracer("test")
    msgs = [{"role": "user", "parts": [{"type": "text", "content": "Hi"}]}]
    with tracer.start_as_current_span("llm") as span:
        span.set_attribute(GenAI.REQUEST_MODEL, "claude-haiku-4-5")
        span.set_attribute(GenAI.INPUT_MESSAGES, json.dumps(msgs))

    assert len(downstream.started) == 1
    assert len(downstream.ended) == 1
    converted = downstream.ended[0]
    attrs = converted.attributes
    assert attrs is not None
    assert attrs[OI.SPAN_KIND] == "LLM"
    assert attrs[OI.LLM_MODEL_NAME] == "claude-haiku-4-5"
    # Delegated ReadableSpan surface still resolves through the wrapper.
    assert converted.name == "llm"
    assert converted.get_span_context() is not None
    assert converted.context is not None
    assert converted.kind is not None
    assert converted.status is not None
    assert converted.start_time is not None
    assert converted.end_time is not None
    assert converted.resource is not None
    assert converted.instrumentation_scope is not None
    assert converted.events == ()
    assert converted.links == ()
    assert converted.parent is None
    assert converted.dropped_attributes == 0
    assert converted.dropped_events == 0
    assert converted.dropped_links == 0
    assert json.loads(converted.to_json())["name"] == "llm"
    assert converted.instrumentation_scope is not None
    assert converted.instrumentation_scope.name == "test"


def test_processor_forwards_unconverted_span_when_no_genai_attrs():
    downstream = _CapturingProcessor()
    tracer = _provider(downstream).get_tracer("test")
    with tracer.start_as_current_span("plain"):
        pass
    # No gen_ai attributes → conversion yields nothing → original forwarded.
    assert downstream.ended[0].name == "plain"
    assert OI.SPAN_KIND not in (downstream.ended[0].attributes or {})


def test_processor_shutdown_and_force_flush_delegate():
    downstream = _CapturingProcessor()
    proc = OpenInferenceSpanProcessor(downstream)
    assert proc.force_flush(123) is True
    assert downstream.flushed is True
    proc.shutdown()
    assert downstream.shutdown_called is True
