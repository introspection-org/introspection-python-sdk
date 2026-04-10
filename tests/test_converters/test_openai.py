"""Tests for OpenAI format conversion to OTel Gen AI Semantic Conventions.

These tests validate that the converter functions produce output that conforms
to the OTel Gen AI semantic convention schemas, using real OpenAI typed objects.
"""

from inline_snapshot import snapshot
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseFunctionToolCallParam,
    ResponseFunctionWebSearch,
    ResponseOutputMessage,
    ResponseReasoningItem,
)
from openai.types.responses.response_function_web_search import ActionSearch
from openai.types.responses.response_input_item_param import (
    FunctionCallOutput,
    Message,
    ResponseInputMessageContentListParam,
)
from openai.types.responses.response_input_text_param import (
    ResponseInputTextParam,
)
from openai.types.responses.response_output_item import McpCall, McpListTools
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_reasoning_item import Summary
from pydantic import TypeAdapter

from introspection_sdk.converters.openai import (
    convert_responses_inputs_to_semconv,
    convert_responses_outputs_to_semconv,
)
from introspection_sdk.schemas.genai import InputMessages, OutputMessages

# Validators for schema compliance
input_messages_validator = TypeAdapter(InputMessages)
output_messages_validator = TypeAdapter(OutputMessages)


class TestInputMessagesSchemaCompliance:
    """Test that input conversions produce schema-compliant output."""

    def test_with_instructions(self):
        """Instructions are returned separately (not part of messages schema)."""
        content: ResponseInputMessageContentListParam = [
            ResponseInputTextParam(type="input_text", text="Hello"),
        ]
        inputs: list[Message] = [
            Message(role="user", content=content, type="message")
        ]
        messages, system_instructions = convert_responses_inputs_to_semconv(
            inputs, "Be helpful"
        )
        input_messages_validator.validate_python(messages)
        assert len(messages) == 1
        assert len(system_instructions) == 1
        assert system_instructions[0].type == "text"

    def test_message_list_input(self):
        """List of messages converts to valid schema."""
        c1: ResponseInputMessageContentListParam = [
            ResponseInputTextParam(type="input_text", text="Hello"),
        ]
        c2: ResponseInputMessageContentListParam = [
            ResponseInputTextParam(type="input_text", text="Hi there!"),
        ]
        inputs: list[Message] = [
            Message(role="user", content=c1, type="message"),
            Message(role="user", content=c2, type="message"),
        ]
        messages, _ = convert_responses_inputs_to_semconv(inputs, None)
        input_messages_validator.validate_python(messages)
        assert len(messages) == 2

    def test_function_call_input(self):
        """Function call input converts to valid schema with tool_call part."""
        inputs: list[ResponseFunctionToolCallParam] = [
            ResponseFunctionToolCallParam(
                type="function_call",
                call_id="call_123",
                name="get_weather",
                arguments='{"city": "Tokyo"}',
            )
        ]
        messages, _ = convert_responses_inputs_to_semconv(inputs, None)
        input_messages_validator.validate_python(messages)
        assert messages[0].role == "assistant"
        assert messages[0].parts[0].type == "tool_call"

    def test_function_call_output_input(self):
        """Function call output input converts to valid schema with tool_call_response."""
        inputs: list[FunctionCallOutput] = [
            FunctionCallOutput(
                type="function_call_output",
                call_id="call_123",
                output="Sunny, 25C",
            )
        ]
        messages, _ = convert_responses_inputs_to_semconv(inputs, None)
        input_messages_validator.validate_python(messages)
        assert messages[0].role == "tool"
        assert messages[0].parts[0].type == "tool_call_response"

    def test_empty_input(self):
        """Empty input produces valid empty list."""
        messages, system_instructions = convert_responses_inputs_to_semconv(
            None, None
        )
        input_messages_validator.validate_python(messages)
        assert messages == []
        assert system_instructions == []


class TestOutputMessagesSchemaCompliance:
    """Test that output conversions produce schema-compliant output."""

    def test_text_output(self):
        """Text output converts to valid schema."""
        outputs = [
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="Hello!", type="output_text", annotations=[]
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert len(messages) == 1
        assert messages[0].role == "assistant"

    def test_function_call_output(self):
        """Function call output converts to valid schema with tool_call part."""
        outputs = [
            ResponseFunctionToolCall(
                id="fc_1",
                type="function_call",
                call_id="call_456",
                name="search",
                arguments='{"query": "test"}',
            )
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert messages[0].parts[0].type == "tool_call"

    def test_multiple_outputs(self):
        """Multiple outputs all convert to valid schema."""
        outputs = [
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="First response",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
            ResponseOutputMessage(
                id="msg_2",
                content=[
                    ResponseOutputText(
                        text="Second response",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert len(messages) == 2

    def test_mixed_output_types(self):
        """Mix of message and function_call outputs converts to valid schema."""
        outputs = [
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="I'll search for that.",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
            ResponseFunctionToolCall(
                id="fc_1",
                type="function_call",
                call_id="call_789",
                name="search",
                arguments="{}",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert messages[0].parts[0].type == "text"
        assert messages[1].parts[0].type == "tool_call"

    def test_empty_output(self):
        """Empty output produces valid empty list."""
        messages = convert_responses_outputs_to_semconv([])
        output_messages_validator.validate_python(messages)
        assert messages == []

    def test_reasoning_with_summary(self):
        """Reasoning item with summary merges thinking part into next message."""
        outputs = [
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[
                    Summary(
                        text="Thinking about the problem...",
                        type="summary_text",
                    ),
                    Summary(
                        text="Breaking it down step by step.",
                        type="summary_text",
                    ),
                ],
            ),
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="The answer is 42.",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [
                        {
                            "type": "thinking",
                            "content": "Thinking about the problem...\nBreaking it down step by step.",
                            "provider_name": "openai",
                        },
                        {"type": "text", "content": "The answer is 42."},
                    ],
                }
            ]
        )

    def test_reasoning_with_empty_summary(self):
        """Reasoning item with empty summary stores encrypted_content as signature."""
        outputs = [
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[],
                encrypted_content="opaque-blob",
            ),
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="The answer is 42.",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [
                        {
                            "type": "thinking",
                            "signature": "opaque-blob",
                            "provider_name": "openai",
                        },
                        {"type": "text", "content": "The answer is 42."},
                    ],
                }
            ]
        )

    def test_web_search_call(self):
        """Web search call produces tool_call + tool_call_response merged into message."""
        outputs = [
            ResponseFunctionWebSearch(
                id="ws_1",
                type="web_search_call",
                status="completed",
                action=ActionSearch(
                    type="search",
                    query="latest SpaceX launch",
                    queries=["latest SpaceX launch"],
                ),
            ),
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="SpaceX launched yesterday.",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [
                        {
                            "type": "tool_call",
                            "name": "web_search",
                            "id": "ws_1",
                            "arguments": '{"query": "latest SpaceX launch"}',
                        },
                        {
                            "type": "tool_call_response",
                            "response": "search completed",
                            "id": "ws_1",
                        },
                        {
                            "type": "text",
                            "content": "SpaceX launched yesterday.",
                        },
                    ],
                }
            ]
        )

    def test_mcp_call(self):
        """MCP call produces tool_call + tool_call_response merged into message."""
        outputs = [
            McpCall(
                id="mcp_1",
                type="mcp_call",
                server_label="deepwiki",
                name="ask_question",
                arguments='{"repo":"openai/agents"}',
                output="The Agent class is the core building block...",
                error=None,
                status="completed",
            ),
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="The Agent class works by...",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [
                        {
                            "type": "tool_call",
                            "name": "deepwiki/ask_question",
                            "id": "mcp_1",
                            "arguments": '{"repo":"openai/agents"}',
                        },
                        {
                            "type": "tool_call_response",
                            "response": "The Agent class is the core building block...",
                            "id": "mcp_1",
                        },
                        {
                            "type": "text",
                            "content": "The Agent class works by...",
                        },
                    ],
                }
            ]
        )

    def test_mcp_list_tools_skipped(self):
        """mcp_list_tools items are skipped (not user-facing)."""
        outputs = [
            McpListTools(
                id="mcpl_1",
                type="mcp_list_tools",
                server_label="deepwiki",
                tools=[],
            ),
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="Hello!", type="output_text", annotations=[]
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [{"type": "text", "content": "Hello!"}],
                }
            ]
        )

    def test_reasoning_and_web_search_combined(self):
        """Reasoning + web search both merge into the final message."""
        outputs = [
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[
                    Summary(
                        text="Let me search for this.", type="summary_text"
                    )
                ],
            ),
            ResponseFunctionWebSearch(
                id="ws_1",
                type="web_search_call",
                status="completed",
                action=ActionSearch(
                    type="search", query="test query", queries=["test query"]
                ),
            ),
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="Here are the results.",
                        type="output_text",
                        annotations=[],
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            ),
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [
                        {
                            "type": "thinking",
                            "content": "Let me search for this.",
                            "provider_name": "openai",
                        },
                        {
                            "type": "tool_call",
                            "name": "web_search",
                            "id": "ws_1",
                            "arguments": '{"query": "test query"}',
                        },
                        {
                            "type": "tool_call_response",
                            "response": "search completed",
                            "id": "ws_1",
                        },
                        {"type": "text", "content": "Here are the results."},
                    ],
                }
            ]
        )

    def test_function_call_has_finish_reason(self):
        """Function call output has finish_reason 'tool-calls'."""
        outputs = [
            ResponseFunctionToolCall(
                id="fc_1",
                type="function_call",
                call_id="call_456",
                name="search",
                arguments='{"q": "test"}',
            )
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "tool-calls",
                    "parts": [
                        {
                            "type": "tool_call",
                            "name": "search",
                            "id": "call_456",
                            "arguments": '{"q": "test"}',
                        }
                    ],
                }
            ]
        )

    def test_message_has_finish_reason_stop(self):
        """Completed message output has finish_reason 'stop'."""
        outputs = [
            ResponseOutputMessage(
                id="msg_1",
                content=[
                    ResponseOutputText(
                        text="Done!", type="output_text", annotations=[]
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        ]
        messages = convert_responses_outputs_to_semconv(outputs)
        output_messages_validator.validate_python(messages)
        assert [m.model_dump(exclude_none=True) for m in messages] == snapshot(
            [
                {
                    "role": "assistant",
                    "finish_reason": "stop",
                    "parts": [{"type": "text", "content": "Done!"}],
                }
            ]
        )
