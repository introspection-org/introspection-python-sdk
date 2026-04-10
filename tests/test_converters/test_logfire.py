"""Tests for Anthropic/Claude format conversion to OTel Gen AI Semantic Conventions.

These tests validate that the converter functions produce output that conforms
to the OTel Gen AI semantic convention schemas.
"""

import json

from pydantic import TypeAdapter

from introspection_sdk.converters.logfire import (
    convert_logfire_messages_to_semconv,
    convert_logfire_response_to_semconv,
    convert_logfire_to_genai,
    is_logfire_span,
)
from introspection_sdk.schemas.genai import (
    InputMessage,
    InputMessages,
    OutputMessage,
    OutputMessages,
    SystemInstruction,
    TextPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)

# Validators for schema compliance
input_messages_validator = TypeAdapter(InputMessages)
output_messages_validator = TypeAdapter(OutputMessages)


class TestIsAnthropicLogfireSpan:
    """Test detection of logfire Anthropic spans."""

    def test_anthropic_span_with_request_data(self):
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "request_data": '{"model":"claude-haiku-4-5","messages":[]}',
        }
        assert is_logfire_span(attrs) is True

    def test_openai_provider_with_request_data(self):
        """Logfire spans from any provider (including OpenAI) should match."""
        attrs = {
            "gen_ai.provider.name": "openai",
            "request_data": '{"model":"gpt-4"}',
        }
        assert is_logfire_span(attrs) is True

    def test_missing_request_data(self):
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-haiku-4-5",
        }
        assert is_logfire_span(attrs) is False

    def test_already_converted(self):
        """Skip spans that already have gen_ai.input.messages."""
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "request_data": '{"model":"claude-haiku-4-5"}',
            "gen_ai.input.messages": '[{"role":"user","parts":[]}]',
        }
        assert is_logfire_span(attrs) is False

    def test_none_attrs(self):
        assert is_logfire_span(None) is False


class TestConvertAnthropicMessagesToSemconv:
    """Test input message conversion from Anthropic format."""

    def test_simple_text_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        result, system = convert_logfire_messages_to_semconv(messages)
        input_messages_validator.validate_python(result)
        assert result == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Hello")],
            )
        ]
        assert system == []

    def test_multi_turn_conversation(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        result, _ = convert_logfire_messages_to_semconv(messages)
        input_messages_validator.validate_python(result)
        assert result == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Hello")],
            ),
            InputMessage(
                role="assistant",
                parts=[TextPart(type="text", content="Hi there!")],
            ),
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="How are you?")],
            ),
        ]

    def test_system_string(self):
        messages = [{"role": "user", "content": "Hello"}]
        result, system = convert_logfire_messages_to_semconv(
            messages, "You are helpful"
        )
        input_messages_validator.validate_python(result)
        assert system == [
            SystemInstruction(type="text", content="You are helpful")
        ]

    def test_system_list(self):
        messages = [{"role": "user", "content": "Hello"}]
        system_param = [{"type": "text", "text": "Be concise"}]
        result, system = convert_logfire_messages_to_semconv(
            messages, system_param
        )
        input_messages_validator.validate_python(result)
        assert system == [SystemInstruction(type="text", content="Be concise")]

    def test_tool_use_content(self):
        """Assistant message with tool_use block."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check the weather."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "get_weather",
                        "input": {"city": "Tokyo"},
                    },
                ],
            }
        ]
        result, _ = convert_logfire_messages_to_semconv(messages)
        input_messages_validator.validate_python(result)
        assert result == [
            InputMessage(
                role="assistant",
                parts=[
                    TextPart(
                        type="text",
                        content="Let me check the weather.",
                    ),
                    ToolCallRequestPart(
                        type="tool_call",
                        id="toolu_123",
                        name="get_weather",
                        arguments={"city": "Tokyo"},
                    ),
                ],
            )
        ]

    def test_tool_result_content(self):
        """User message with tool_result block."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "Sunny, 25C",
                    }
                ],
            }
        ]
        result, _ = convert_logfire_messages_to_semconv(messages)
        input_messages_validator.validate_python(result)
        assert result == [
            InputMessage(
                role="user",
                parts=[
                    ToolCallResponsePart(
                        type="tool_call_response",
                        id="toolu_123",
                        response="Sunny, 25C",
                    )
                ],
            )
        ]

    def test_tool_result_with_list_content(self):
        """Tool result with structured list content."""
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_456",
                        "content": [
                            {"type": "text", "text": "Temperature: 25C"},
                            {"type": "text", "text": "Humidity: 60%"},
                        ],
                    }
                ],
            }
        ]
        result, _ = convert_logfire_messages_to_semconv(messages)
        input_messages_validator.validate_python(result)
        assert result == [
            InputMessage(
                role="user",
                parts=[
                    ToolCallResponsePart(
                        type="tool_call_response",
                        id="toolu_456",
                        response="Temperature: 25C Humidity: 60%",
                    )
                ],
            )
        ]

    def test_empty_messages(self):
        result, system = convert_logfire_messages_to_semconv([])
        input_messages_validator.validate_python(result)
        assert result == []
        assert system == []

    def test_full_tool_use_conversation(self):
        """Complete multi-turn conversation with tool use."""
        messages = [
            {"role": "user", "content": "What's the weather in Tokyo?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_001",
                        "name": "get_weather",
                        "input": {"city": "Tokyo"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_001",
                        "content": "Clear, 68F",
                    }
                ],
            },
        ]
        result, _ = convert_logfire_messages_to_semconv(messages)
        input_messages_validator.validate_python(result)
        assert result == [
            InputMessage(
                role="user",
                parts=[
                    TextPart(
                        type="text",
                        content="What's the weather in Tokyo?",
                    )
                ],
            ),
            InputMessage(
                role="assistant",
                parts=[
                    ToolCallRequestPart(
                        type="tool_call",
                        id="toolu_001",
                        name="get_weather",
                        arguments={"city": "Tokyo"},
                    )
                ],
            ),
            InputMessage(
                role="user",
                parts=[
                    ToolCallResponsePart(
                        type="tool_call_response",
                        id="toolu_001",
                        response="Clear, 68F",
                    )
                ],
            ),
        ]


class TestConvertAnthropicResponseToSemconv:
    """Test output message conversion from logfire response_data format."""

    def test_text_response(self):
        response_data = {
            "message": {"role": "assistant", "content": "Hello!"},
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        result = convert_logfire_response_to_semconv(response_data)
        output_messages_validator.validate_python(result)
        assert result == [
            OutputMessage(
                role="assistant",
                parts=[TextPart(type="text", content="Hello!")],
            )
        ]

    def test_tool_call_response(self):
        """Response with tool calls (logfire v1 format)."""
        response_data = {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "toolu_789",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Tokyo"}',
                        },
                    }
                ],
            },
            "usage": {"input_tokens": 15, "output_tokens": 20},
        }
        result = convert_logfire_response_to_semconv(response_data)
        output_messages_validator.validate_python(result)
        assert result == [
            OutputMessage(
                role="assistant",
                parts=[
                    ToolCallRequestPart(
                        type="tool_call",
                        id="toolu_789",
                        name="get_weather",
                        arguments={"city": "Tokyo"},
                    )
                ],
            )
        ]

    def test_mixed_text_and_tool_calls(self):
        response_data = {
            "message": {
                "role": "assistant",
                "content": "Let me check that.",
                "tool_calls": [
                    {
                        "id": "toolu_001",
                        "function": {
                            "name": "search",
                            "arguments": '{"q":"test"}',
                        },
                    }
                ],
            },
        }
        result = convert_logfire_response_to_semconv(response_data)
        output_messages_validator.validate_python(result)
        assert result == [
            OutputMessage(
                role="assistant",
                parts=[
                    TextPart(
                        type="text",
                        content="Let me check that.",
                    ),
                    ToolCallRequestPart(
                        type="tool_call",
                        id="toolu_001",
                        name="search",
                        arguments={"q": "test"},
                    ),
                ],
            )
        ]

    def test_empty_response(self):
        result = convert_logfire_response_to_semconv({})
        assert result == []

    def test_no_message(self):
        result = convert_logfire_response_to_semconv(
            {"usage": {"input_tokens": 10}}
        )
        assert result == []


class TestConvertAnthropicToGenai:
    """Test the main conversion function with full span attributes."""

    def test_basic_chat(self):
        """Simple chat with request_data and response_data JSON strings."""
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-haiku-4-5",
            "gen_ai.response.model": "claude-haiku-4-5-20250123",
            "gen_ai.response.id": "msg_abc123",
            "gen_ai.usage.input_tokens": 25,
            "gen_ai.usage.output_tokens": 10,
            "request_data": json.dumps(
                {
                    "model": "claude-haiku-4-5",
                    "messages": [{"role": "user", "content": "Say hello."}],
                    "max_tokens": 100,
                }
            ),
            "response_data": json.dumps(
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "usage": {"input_tokens": 25, "output_tokens": 10},
                }
            ),
        }
        result = convert_logfire_to_genai(attrs)
        assert result.request_model == "claude-haiku-4-5"
        assert result.system == "anthropic"
        assert result.response_id == "msg_abc123"
        assert result.input_tokens == 25
        assert result.output_tokens == 10
        assert result.input_messages == [
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content="Say hello.")],
            )
        ]
        assert result.output_messages == [
            OutputMessage(
                role="assistant",
                parts=[TextPart(type="text", content="Hello!")],
            )
        ]

    def test_with_system_prompt(self):
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-haiku-4-5",
            "gen_ai.usage.input_tokens": 30,
            "gen_ai.usage.output_tokens": 15,
            "request_data": json.dumps(
                {
                    "model": "claude-haiku-4-5",
                    "system": "You are a helpful assistant.",
                    "messages": [{"role": "user", "content": "Hello"}],
                }
            ),
            "response_data": json.dumps(
                {
                    "message": {"role": "assistant", "content": "Hi!"},
                    "usage": {"input_tokens": 30, "output_tokens": 15},
                }
            ),
        }
        result = convert_logfire_to_genai(attrs)
        assert result.system_instructions == [
            SystemInstruction(
                type="text",
                content="You are a helpful assistant.",
            )
        ]

    def test_with_tool_use(self):
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-haiku-4-5",
            "gen_ai.usage.input_tokens": 50,
            "gen_ai.usage.output_tokens": 30,
            "request_data": json.dumps(
                {
                    "model": "claude-haiku-4-5",
                    "messages": [
                        {
                            "role": "user",
                            "content": "What's the weather?",
                        }
                    ],
                    "tools": [
                        {
                            "name": "get_weather",
                            "description": "Get weather",
                            "input_schema": {"type": "object"},
                        }
                    ],
                }
            ),
            "response_data": json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "toolu_001",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"SF"}',
                                },
                            }
                        ],
                    },
                    "usage": {"input_tokens": 50, "output_tokens": 30},
                }
            ),
        }
        result = convert_logfire_to_genai(attrs)
        assert result.output_messages == [
            OutputMessage(
                role="assistant",
                parts=[
                    ToolCallRequestPart(
                        type="tool_call",
                        id="toolu_001",
                        name="get_weather",
                        arguments={"city": "SF"},
                    )
                ],
            )
        ]

    def test_none_attrs(self):
        result = convert_logfire_to_genai(None)
        assert result.request_model is None
        assert result.input_messages is None
        assert result.output_messages is None

    def test_invalid_json_request_data(self):
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "request_data": "not valid json",
        }
        result = convert_logfire_to_genai(attrs)
        assert result.input_messages is None

    def test_to_attributes_output(self):
        """Verify to_attributes() produces the expected gen_ai.* keys."""
        attrs = {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-haiku-4-5",
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 5,
            "request_data": json.dumps(
                {
                    "model": "claude-haiku-4-5",
                    "messages": [{"role": "user", "content": "Hi"}],
                }
            ),
            "response_data": json.dumps(
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                }
            ),
        }
        result = convert_logfire_to_genai(attrs)
        otel_attrs = result.to_attributes()
        assert "gen_ai.request.model" in otel_attrs
        assert "gen_ai.system" in otel_attrs
        assert "gen_ai.input.messages" in otel_attrs
        assert "gen_ai.output.messages" in otel_attrs
        assert otel_attrs["gen_ai.system"] == "anthropic"
