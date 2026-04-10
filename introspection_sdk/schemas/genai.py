"""OTel Gen AI Semantic Convention Pydantic models.

Based on the OpenTelemetry Gen AI semantic conventions:
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-input-messages.json
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-output-messages.json
"""

from typing import Annotated, Any, Literal

try:
    from pydantic import BaseModel, Field
except ImportError as e:
    raise ImportError(
        "pydantic is required to use the schemas module. "
        "Install it with: pip install 'introspection-sdk[test]'"
    ) from e

__all__ = [
    "TextPart",
    "ThinkingPart",
    "ToolCallRequestPart",
    "ToolCallResponsePart",
    "MessagePart",
    "InputMessage",
    "OutputMessage",
    "InputMessages",
    "OutputMessages",
    "SystemInstruction",
    "SystemInstructions",
    "ToolDefinition",
    "ToolDefinitions",
]


class TextPart(BaseModel):
    """Text content part."""

    type: Literal["text"] = Field(
        description="Part type discriminator, always ``'text'``.",
    )
    content: str = Field(description="The text content.")


class ThinkingPart(BaseModel):
    """Reasoning/thinking content part (e.g. chain-of-thought from reasoning models)."""

    type: Literal["thinking"] = Field(
        description="Part type discriminator, always ``'thinking'``.",
    )
    content: str | None = Field(
        default=None, description="The reasoning/thinking summary content."
    )
    signature: str | None = Field(
        default=None,
        description="Encrypted reasoning signature (maps to OpenAI encrypted_content, Anthropic signature/redacted_thinking data).",
    )
    provider_name: str | None = Field(
        default=None,
        description="Provider that produced this thinking block (e.g. ``'anthropic'``, ``'openai'``). Used to reconstruct the correct wire format on replay.",
    )


class ToolCallRequestPart(BaseModel):
    """Tool/function call request part."""

    type: Literal["tool_call"] = Field(
        description="Part type discriminator, always ``'tool_call'``.",
    )
    name: str = Field(description="Name of the tool/function being called.")
    id: str | None = Field(
        default=None, description="Provider-assigned tool call ID."
    )
    arguments: Any = Field(
        default=None,
        description="Arguments passed to the tool (dict or JSON string).",
    )


class ToolCallResponsePart(BaseModel):
    """Tool/function call response part."""

    type: Literal["tool_call_response"] = Field(
        description="Part type discriminator, always ``'tool_call_response'``.",
    )
    response: Any = Field(description="The tool's response payload.")
    id: str | None = Field(
        default=None,
        description="Tool call ID this response corresponds to.",
    )


# Union type for message parts - uses discriminated union on 'type' field
MessagePart = Annotated[
    TextPart | ThinkingPart | ToolCallRequestPart | ToolCallResponsePart,
    Field(discriminator="type"),
]
"""Discriminated union of :class:`TextPart`, :class:`ThinkingPart`, :class:`ToolCallRequestPart`, and :class:`ToolCallResponsePart`."""


class InputMessage(BaseModel):
    """Input message in OTel Gen AI semantic convention format."""

    role: Literal["system", "user", "assistant", "tool"] = Field(
        description="Message role: ``'system'``, ``'user'``, ``'assistant'``, or ``'tool'``.",
    )
    parts: list[MessagePart] = Field(
        description="Ordered list of content parts.",
    )
    name: str | None = Field(default=None, description="Optional sender name.")


class OutputMessage(BaseModel):
    """Output message in OTel Gen AI semantic convention format."""

    role: Literal["system", "user", "assistant", "tool"] = Field(
        description="Message role: ``'system'``, ``'user'``, ``'assistant'``, or ``'tool'``.",
    )
    parts: list[MessagePart] = Field(
        description="Ordered list of content parts.",
    )
    finish_reason: str | None = Field(
        default=None,
        description="Why the model stopped generating (e.g. ``'stop'``, ``'max_tokens'``, ``'tool_calls'``).",
    )
    name: str | None = Field(default=None, description="Optional sender name.")


# Type aliases for validating lists of messages
InputMessages = list[InputMessage]
"""List of :class:`InputMessage` instances."""

OutputMessages = list[OutputMessage]
"""List of :class:`OutputMessage` instances."""


class SystemInstruction(BaseModel):
    """A single system instruction part (text content)."""

    type: Literal["text"] = Field(
        default="text",
        description="Part type discriminator, always ``'text'``.",
    )
    content: str = Field(description="The instruction text content.")


SystemInstructions = list[SystemInstruction]
"""List of :class:`SystemInstruction` instances."""


class ToolDefinition(BaseModel):
    """A tool/function definition available to the model."""

    type: str | None = Field(
        default=None,
        description="Tool type (e.g. ``'function'``).",
    )
    name: str | None = Field(
        default=None,
        description="Name of the tool/function.",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of what the tool does.",
    )
    parameters: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema of the tool's parameters.",
    )


ToolDefinitions = list[ToolDefinition]
"""List of :class:`ToolDefinition` instances."""
