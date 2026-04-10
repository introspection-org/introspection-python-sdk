"""Logfire format conversion functions for OTel Gen AI Semantic Conventions.

Converts logfire-instrumented spans (which store `request_data` and
`response_data` as JSON strings) to the standardized OTel Gen AI Semantic
Convention format for gen_ai.input.messages, gen_ai.output.messages, and
gen_ai.system_instructions. Works for any provider (OpenAI, Anthropic, etc.).
"""

__all__ = [
    "convert_logfire_to_genai",
    "is_logfire_span",
]

import json
import logging
from typing import Any, Literal

from opentelemetry.util.types import Attributes
from pydantic import BaseModel, ConfigDict

from introspection_sdk.schemas.genai import (
    InputMessage,
    MessagePart,
    OutputMessage,
    SystemInstruction,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.types import GenAiAttributes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models for logfire request_data / response_data structures.
# All use extra="allow" so unknown fields don't cause validation errors.
# ---------------------------------------------------------------------------


class ContentPart(BaseModel):
    """A content block inside a logfire message."""

    model_config = ConfigDict(extra="allow")

    type: str = "text"
    text: str = ""
    id: str = ""
    name: str = ""
    input: Any = None
    content: Any = None
    tool_use_id: str = ""


class Message(BaseModel):
    """A message dict inside logfire request_data.messages."""

    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str | list[dict[str, Any]] | None = None


class ToolCallFunction(BaseModel):
    """The ``function`` sub-dict inside a tool call."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    arguments: str | dict[str, Any] | None = None


class ToolCall(BaseModel):
    """An OpenAI-style tool call dict in the response message."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    function: ToolCallFunction = ToolCallFunction()


class ResponseMessage(BaseModel):
    """The ``message`` dict inside logfire response_data."""

    model_config = ConfigDict(extra="allow")

    role: str = "assistant"
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[ToolCall] | None = None


class ResponseData(BaseModel):
    """Top-level logfire response_data structure."""

    model_config = ConfigDict(extra="allow")

    message: ResponseMessage | None = None
    usage: dict[str, Any] | None = None


class RequestData(BaseModel):
    """Top-level logfire request_data structure."""

    model_config = ConfigDict(extra="allow")

    messages: list[Message] = []
    system: str | list[dict[str, Any]] | None = None
    model: str | None = None


def is_logfire_span(attrs: Attributes | None) -> bool:
    """Check if a span is a logfire-instrumented LLM span needing conversion.

    Returns ``True`` if the span has ``request_data`` and does NOT already
    have ``gen_ai.input.messages`` (i.e., it hasn't been converted yet /
    isn't using logfire ``version='latest'``). Matches any provider
    (OpenAI, Anthropic, etc.).

    Args:
        attrs: Span attributes to inspect.

    Returns:
        ``True`` if the span needs logfire-to-GenAI conversion.
    """
    if attrs is None:
        return False
    if "request_data" not in attrs:
        return False
    # Skip if already has gen_ai.input.messages (e.g., logfire version='latest')
    if attrs.get("gen_ai.input.messages"):
        return False
    return True


def _convert_content_part(
    part: ContentPart,
) -> TextPart | ThinkingPart | ToolCallRequestPart | ToolCallResponsePart:
    """Convert a single logfire content part to gen_ai semconv format."""
    if part.type == "text":
        return TextPart(type="text", content=part.text)

    if part.type == "tool_use":
        return ToolCallRequestPart(
            type="tool_call",
            id=part.id,
            name=part.name,
            arguments=part.input,
        )

    if part.type == "tool_result":
        result_content = part.content
        if isinstance(result_content, list):
            text_parts: list[str] = []
            for p in result_content:
                if isinstance(p, dict) and p.get("type") == "text":
                    text_parts.append(str(p.get("text", "")))
                elif isinstance(p, str):
                    text_parts.append(p)
            response = " ".join(text_parts)
        else:
            response = str(result_content) if result_content else ""

        return ToolCallResponsePart(
            type="tool_call_response",
            id=part.tool_use_id,
            response=response,
        )

    if part.type == "thinking":
        thinking_text = getattr(part, "thinking", "") or None
        signature = getattr(part, "signature", None) or None
        return ThinkingPart(
            type="thinking",
            content=thinking_text,
            signature=signature,
            provider_name="anthropic",
        )

    # Unknown type — return as text
    return TextPart(type="text", content=part.text)


def convert_logfire_messages_to_semconv(
    messages: list[dict[str, Any]] | list[Message],
    system: str | list[dict[str, Any]] | None = None,
) -> tuple[list[InputMessage], list[SystemInstruction]]:
    """Convert logfire messages format to gen_ai semconv format.

    Args:
        messages: List of logfire message dicts or validated Message models.
        system: System parameter (string or list of content blocks).

    Returns:
        Tuple of (input_messages, system_instructions) as typed models.
    """
    validated_messages = [
        m if isinstance(m, Message) else Message.model_validate(m)
        for m in messages
    ]
    input_messages: list[InputMessage] = []
    system_instructions: list[SystemInstruction] = []

    # Handle system parameter
    if system:
        if isinstance(system, str):
            system_instructions.append(
                SystemInstruction(type="text", content=system)
            )
        elif isinstance(system, list):
            for part in system:
                if isinstance(part, dict) and part.get("type") == "text":
                    system_instructions.append(
                        SystemInstruction(
                            type="text", content=part.get("text", "")
                        )
                    )

    for msg in validated_messages:
        content = msg.content
        parts: list[MessagePart] = []

        if content is not None:
            if isinstance(content, str):
                parts.append(TextPart(type="text", content=content))
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        parts.append(
                            _convert_content_part(
                                ContentPart.model_validate(item)
                            )
                        )
                    elif isinstance(item, str):
                        parts.append(TextPart(type="text", content=item))

        input_messages.append(InputMessage(role=msg.role, parts=parts))

    return input_messages, system_instructions


def convert_logfire_response_to_semconv(
    response_data: dict[str, Any] | ResponseData,
) -> list[OutputMessage]:
    """Convert logfire's response_data to gen_ai semconv output messages.

    Args:
        response_data: Raw dict or validated ResponseData model.

    Returns:
        List of output messages as typed models.
    """
    validated = (
        response_data
        if isinstance(response_data, ResponseData)
        else ResponseData.model_validate(response_data)
    )
    message = validated.message
    if message is None:
        return []

    parts: list[MessagePart] = []

    # Text content
    if message.content and isinstance(message.content, str):
        parts.append(TextPart(type="text", content=message.content))

    # Tool calls (logfire v1 format — OpenAI function-calling shape)
    if message.tool_calls:
        for tc in message.tool_calls:
            arguments: Any = tc.function.arguments
            # arguments may be a JSON string; try to parse it
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    pass

            parts.append(
                ToolCallRequestPart(
                    type="tool_call",
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                )
            )

    if not parts:
        return []

    return [OutputMessage(role="assistant", parts=parts)]


def convert_logfire_to_genai(attrs: Attributes | None) -> GenAiAttributes:
    """Convert logfire span attributes to GenAI semconv format.

    Extracts request_data and response_data JSON strings from span attributes,
    validates them into Pydantic models, converts messages to gen_ai semconv
    format, and returns GenAiAttributes.

    Only populates fields that are missing from the span — gen_ai.request.model,
    gen_ai.usage.*, gen_ai.response.id are already set by logfire and preserved.

    Args:
        attrs: Span attributes from a logfire-instrumented span.

    Returns:
        GenAiAttributes with input_messages, output_messages, system_instructions,
        and system populated.
    """
    if attrs is None:
        return GenAiAttributes()

    # Parse and validate request_data (may be JSON string or dict)
    request_data: RequestData | None = None
    request_data_raw = attrs.get("request_data")
    try:
        if isinstance(request_data_raw, str):
            request_data = RequestData.model_validate_json(request_data_raw)
        elif isinstance(request_data_raw, dict):
            request_data = RequestData.model_validate(request_data_raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse request_data")

    # Parse and validate response_data (may be JSON string or dict)
    response_data: ResponseData | None = None
    response_data_raw = attrs.get("response_data")
    try:
        if isinstance(response_data_raw, str):
            response_data = ResponseData.model_validate_json(response_data_raw)
        elif isinstance(response_data_raw, dict):
            response_data = ResponseData.model_validate(response_data_raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse response_data")

    # Extract input messages and system instructions
    input_messages: list[InputMessage] | None = None
    system_instructions: list[SystemInstruction] | None = None
    if request_data:
        if request_data.messages or request_data.system:
            input_messages, system_instructions = (
                convert_logfire_messages_to_semconv(
                    request_data.messages, request_data.system
                )
            )

    # Extract output messages
    output_messages: list[OutputMessage] | None = None
    if response_data:
        output_messages = convert_logfire_response_to_semconv(response_data)

    # Extract model from request_data (fallback if not in flat attributes)
    model = attrs.get("gen_ai.request.model")
    if not model and request_data:
        model = request_data.model

    # Extract token usage (already available as flat attributes from logfire)
    input_tokens = attrs.get("gen_ai.usage.input_tokens")
    output_tokens = attrs.get("gen_ai.usage.output_tokens")

    # Extract response ID (already available from logfire)
    response_id = attrs.get("gen_ai.response.id")

    # Infer system from provider attribute (works for openai, anthropic, etc.)
    system = attrs.get("gen_ai.system") or attrs.get("gen_ai.provider.name")

    return GenAiAttributes(
        request_model=model if isinstance(model, str) else None,
        system=system if isinstance(system, str) else None,
        input_messages=input_messages or None,
        output_messages=output_messages or None,
        system_instructions=system_instructions or None,
        response_id=response_id if isinstance(response_id, str) else None,
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens
        if isinstance(output_tokens, int)
        else None,
    )
