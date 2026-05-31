"""Tests for the OpenInference → GenAI semconv converter.

All functions are pure transforms over flattened OpenInference attribute
dicts; ``ConvertedReadableSpan`` is exercised against a real OTel span.
No mocks.
"""

from __future__ import annotations

import json

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.converters.openinference import (
    ConvertedReadableSpan,
    convert_openinference_to_genai,
    extract_input_messages,
    extract_model_name,
    extract_output_messages,
    extract_response_id,
    extract_system,
    extract_system_instructions,
    extract_token_usage,
    extract_tool_definitions,
    is_openinference_span,
)
from introspection_sdk.schemas.genai import (
    MessagePart,
    TextPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.types import OpenInferenceSemconv as OI

IN = OI.LLM_INPUT_MESSAGES
OUT = OI.LLM_OUTPUT_MESSAGES


def _text(part: MessagePart) -> str:
    assert isinstance(part, TextPart)
    return part.content


# --- scalar extractors ----------------------------------------------


def test_extract_model_name_and_system():
    attrs = {OI.LLM_MODEL_NAME: "gpt-4o", OI.LLM_SYSTEM: "openai"}
    assert extract_model_name(attrs) == "gpt-4o"
    assert extract_system(attrs) == "openai"


def test_scalar_extractors_handle_none_and_missing():
    assert extract_model_name(None) is None
    assert extract_system(None) is None
    assert extract_model_name({}) is None
    assert extract_token_usage(None) == {}


def test_extract_token_usage_including_cache():
    attrs = {
        OI.LLM_TOKEN_COUNT_PROMPT: 10,
        OI.LLM_TOKEN_COUNT_COMPLETION: 4,
        "llm.token_count.prompt_details.cache_write": 3,
        "llm.token_count.prompt_details.cache_read": 2,
    }
    usage = extract_token_usage(attrs)
    assert usage["gen_ai.usage.input_tokens"] == 10
    assert usage["gen_ai.usage.output_tokens"] == 4
    assert usage["gen_ai.usage.cache_creation.input_tokens"] == 3
    assert usage["gen_ai.usage.cache_read.input_tokens"] == 2


# --- response id ----------------------------------------------------


def test_response_id_prefers_existing_attribute():
    assert extract_response_id({"gen_ai.response.id": "resp_x"}) == "resp_x"


def test_response_id_from_output_value_top_level():
    attrs = {OI.OUTPUT_VALUE: json.dumps({"id": "chatcmpl-1"})}
    assert extract_response_id(attrs) == "chatcmpl-1"


def test_response_id_from_langchain_nested_generations():
    payload = {
        "generations": [
            [
                {
                    "message": {
                        "kwargs": {"response_metadata": {"id": "resp_nested"}}
                    }
                }
            ]
        ]
    }
    attrs = {OI.OUTPUT_VALUE: json.dumps(payload)}
    assert extract_response_id(attrs) == "resp_nested"


def test_response_id_none_when_absent_or_invalid():
    assert extract_response_id(None) is None
    assert extract_response_id({OI.OUTPUT_VALUE: "{not json"}) is None
    assert extract_response_id({OI.OUTPUT_VALUE: json.dumps([1, 2])}) is None


# --- tool definitions -----------------------------------------------


def test_tool_definitions_langchain_function_wrapper():
    schema = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Weather",
            "parameters": {"type": "object"},
        },
    }
    attrs = {f"{OI.LLM_TOOLS}.0.{OI.TOOL_JSON_SCHEMA}": json.dumps(schema)}
    (tool,) = extract_tool_definitions(attrs)
    assert tool.name == "get_weather"
    assert tool.description == "Weather"


def test_tool_definitions_flat_schema():
    schema = {"name": "calc", "parameters": {}}
    attrs = {f"{OI.LLM_TOOLS}.0.{OI.TOOL_JSON_SCHEMA}": json.dumps(schema)}
    (tool,) = extract_tool_definitions(attrs)
    assert tool.name == "calc"
    assert tool.type == "function"


def test_tool_definitions_skip_unparseable_schema():
    attrs = {f"{OI.LLM_TOOLS}.0.{OI.TOOL_JSON_SCHEMA}": "{not json"}
    assert extract_tool_definitions(attrs) == []


def test_tool_definitions_none():
    assert extract_tool_definitions(None) == []


# --- messages -------------------------------------------------------


def test_input_messages_text_and_tool_call():
    attrs = {
        f"{IN}.0.message.role": "user",
        f"{IN}.0.message.content": "Hello",
        f"{IN}.1.message.role": "assistant",
        f"{IN}.1.message.tool_calls.0.tool_call.id": "call_1",
        f"{IN}.1.message.tool_calls.0.tool_call.function.name": "search",
        f"{IN}.1.message.tool_calls.0.tool_call.function.arguments": '{"q":"x"}',
    }
    msgs, sys = extract_input_messages(attrs)
    assert sys == []
    assert msgs[0].role == "user"
    assert _text(msgs[0].parts[0]) == "Hello"
    tool_part = msgs[1].parts[0]
    assert isinstance(tool_part, ToolCallRequestPart)
    assert tool_part.name == "search"


def test_input_messages_tool_response_json_parsed():
    attrs = {
        f"{IN}.0.message.role": "tool",
        f"{IN}.0.message.tool_call_id": "call_9",
        f"{IN}.0.message.content": '{"temp": 70}',
    }
    msgs, _ = extract_input_messages(attrs)
    part = msgs[0].parts[0]
    assert isinstance(part, ToolCallResponsePart)
    assert part.id == "call_9"
    assert part.response == {"temp": 70}


def test_input_messages_multimodal_contents():
    attrs = {
        f"{IN}.0.message.role": "user",
        f"{IN}.0.message.contents.0.message_content.type": "text",
        f"{IN}.0.message.contents.0.message_content.text": "block-text",
    }
    msgs, _ = extract_input_messages(attrs)
    assert _text(msgs[0].parts[0]) == "block-text"


def test_output_messages_with_tool_call():
    attrs = {
        f"{OUT}.0.message.role": "assistant",
        f"{OUT}.0.message.content": "Done",
    }
    msgs = extract_output_messages(attrs)
    assert msgs[0].role == "assistant"
    assert _text(msgs[0].parts[0]) == "Done"


# --- system instructions --------------------------------------------


def test_system_instructions_from_system_role_message():
    attrs = {
        f"{IN}.0.message.role": "system",
        f"{IN}.0.message.content": "Be terse",
    }
    sys = extract_system_instructions(attrs)
    assert sys[0].content == "Be terse"
    # And the system message is stripped from input_messages.
    msgs, sys2 = extract_input_messages(attrs)
    assert msgs == []
    assert sys2[0].content == "Be terse"


def test_system_instructions_from_input_value_anthropic_string():
    attrs = {OI.INPUT_VALUE: json.dumps({"system": "You are helpful"})}
    sys = extract_system_instructions(attrs)
    assert sys[0].content == "You are helpful"


def test_system_instructions_from_input_value_anthropic_blocks():
    attrs = {
        OI.INPUT_VALUE: json.dumps(
            {"system": [{"type": "text", "text": "blk"}]}
        )
    }
    assert extract_system_instructions(attrs)[0].content == "blk"


def test_system_instructions_from_responses_api_instructions():
    attrs = {OI.INPUT_VALUE: json.dumps({"instructions": "do this"})}
    assert extract_system_instructions(attrs)[0].content == "do this"


def test_system_instructions_invalid_json_returns_empty():
    assert extract_system_instructions({OI.INPUT_VALUE: "{bad"}) == []
    assert extract_system_instructions(None) == []


# --- top-level convert ----------------------------------------------


def test_convert_full_span():
    attrs = {
        OI.LLM_MODEL_NAME: "gpt-4o",
        OI.LLM_SYSTEM: "openai",
        OI.LLM_TOKEN_COUNT_PROMPT: 7,
        OI.LLM_TOKEN_COUNT_COMPLETION: 3,
        f"{IN}.0.message.role": "user",
        f"{IN}.0.message.content": "Hi",
        f"{OUT}.0.message.role": "assistant",
        f"{OUT}.0.message.content": "Hello",
    }
    result = convert_openinference_to_genai(attrs)
    assert result.request_model == "gpt-4o"
    assert result.system == "openai"
    assert result.input_tokens == 7
    assert result.output_tokens == 3
    assert result.input_messages is not None
    assert result.output_messages is not None


def test_convert_tool_span_translates_output_value():
    attrs = {
        "openinference.span.kind": "TOOL",
        "output.value": "tool result text",
    }
    result = convert_openinference_to_genai(attrs)
    assert result.output_messages is not None
    part = result.output_messages[0].parts[0]
    assert isinstance(part, ToolCallResponsePart)
    assert part.response == "tool result text"


# --- is_openinference_span ------------------------------------------


def test_is_openinference_span():
    assert is_openinference_span("openinference.instrumentation.openai")
    assert not is_openinference_span("langchain")
    assert not is_openinference_span(None)


# --- ConvertedReadableSpan ------------------------------------------


def _real_span():
    provider = TracerProvider()
    tracer = provider.get_tracer("openinference.test")
    with tracer.start_as_current_span("llm") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute(OI.LLM_MODEL_NAME, "gpt-4o")
        span.set_attribute("keep.me", "yes")
    # After the ``with`` block the span has ended and is a ReadableSpan.
    return span


def test_converted_span_merges_and_filters_attributes():
    original = _real_span()
    converted = convert_openinference_to_genai(original.attributes)
    wrapped = ConvertedReadableSpan(original, converted)
    attrs = wrapped.attributes
    assert attrs is not None
    # llm.* attributes are filtered out, replaced by gen_ai.*
    assert OI.LLM_MODEL_NAME not in attrs
    assert attrs["gen_ai.request.model"] == "gpt-4o"
    # Non-filtered originals are preserved.
    assert attrs["keep.me"] == "yes"
    # LLM spans get a default operation name for the conversation view.
    assert attrs["gen_ai.operation.name"] == "chat"


def test_converted_span_delegates_readablespan_surface():
    original = _real_span()
    wrapped = ConvertedReadableSpan(
        original, convert_openinference_to_genai(original.attributes)
    )
    assert wrapped.name == "llm"
    assert wrapped.get_span_context() is original.get_span_context()
    assert wrapped.context is original.context
    assert wrapped.parent is original.parent
    assert wrapped.resource is original.resource
    assert wrapped.status is original.status
    assert wrapped.kind is original.kind
    assert wrapped.start_time == original.start_time
    assert wrapped.end_time == original.end_time
    assert wrapped.events == original.events
    assert wrapped.links == original.links
    assert wrapped.dropped_attributes == original.dropped_attributes
    assert wrapped.dropped_events == original.dropped_events
    assert wrapped.dropped_links == original.dropped_links
    assert wrapped.instrumentation_scope is original.instrumentation_scope
    assert json.loads(wrapped.to_json())["name"] == "llm"
