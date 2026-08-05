"""OTel Gen AI Semantic Convention Pydantic models.

Based on the OpenTelemetry Gen AI semantic conventions:
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-input-messages.json
- https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-output-messages.json
"""

from typing import Annotated, Any, Literal

try:
    from pydantic import (
        BaseModel,
        ConfigDict,
        Discriminator,
        Field,
        SerializerFunctionWrapHandler,
        Tag,
        model_serializer,
    )
except ImportError as e:
    raise ImportError(
        "pydantic is required to use the schemas module. "
        "Install it with: pip install 'introspection-sdk[test]'"
    ) from e

__all__ = [
    "OmitNoneModel",
    "BinaryPart",
    "CompactionPart",
    "FilePart",
    "GenericPart",
    "TextPart",
    "ThinkingPart",
    "UrlPart",
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


class OmitNoneModel(BaseModel):
    """Base whose serialization drops ``None``-valued keys.

    The semantic conventions describe attributes that are *absent* when they
    have no value, not attributes that are present and null. Emitting
    ``"finish_reason": null`` on every user message asserts a finish reason
    exists and is null, which is a different claim from "this message has no
    finish reason" — and it is the claim a reader then has to defend against.

    This applies on both sides: it is what these models serialize into
    ``gen_ai.input.messages`` on an emitted span, and what they serialize back
    out when a conversation is read. Applying it at the base rather than at
    each call site keeps the two consistent, which matters because a round trip
    through the API should be an identity.
    """

    @model_serializer(mode="wrap")
    def _omit_none(self, handler: SerializerFunctionWrapHandler) -> Any:
        serialized = handler(self)
        if isinstance(serialized, dict):
            return {
                key: value
                for key, value in serialized.items()
                if value is not None
            }
        return serialized


class TextPart(OmitNoneModel):
    """Text content part."""

    type: Literal["text"] = Field(
        default="text",
        description="Part type discriminator, always ``'text'``.",
    )
    content: str = Field(default="", description="The text content.")
    text_signature: str | None = Field(
        default=None,
        description="Opaque per-block signature for replay continuity.",
    )


class ThinkingPart(OmitNoneModel):
    """Reasoning content produced by the model.

    ``thinking`` is the canonical name here, matching the vocabulary the
    platform writes and the one Pydantic AI and the provider SDKs use. The
    semantic conventions call this ``reasoning``; that spelling is accepted so a
    spec-shaped part parses, and it normalizes to ``thinking`` on the way in.

    The alias is permanent rather than transitional. Telemetry is append-only:
    a part type is *stored bytes*, so both spellings stay readable for as long
    as spans written with either one exist.
    """

    type: Literal["thinking", "reasoning"] = Field(
        default="thinking",
        description="Part type discriminator. ``'thinking'`` is canonical; ``'reasoning'`` is the semantic-convention spelling and is accepted on read.",
    )
    content: str | None = Field(
        default=None, description="The thinking/reasoning summary content."
    )
    signature: str | None = Field(
        default=None,
        description="Encrypted reasoning signature (maps to OpenAI encrypted_content, Anthropic signature/redacted_thinking data).",
    )
    provider_name: str | None = Field(
        default=None,
        description="Provider that produced this thinking block (e.g. ``'anthropic'``, ``'openai'``). Used to reconstruct the correct wire format on replay.",
    )
    redacted: bool | None = Field(
        default=None,
        description="True when the thinking content was redacted but the signed payload is preserved.",
    )


class ToolCallRequestPart(OmitNoneModel):
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


class ToolCallResponsePart(OmitNoneModel):
    """Tool/function call response part."""

    type: Literal["tool_call_response"] = Field(
        description="Part type discriminator, always ``'tool_call_response'``.",
    )
    response: Any = Field(description="The tool's response payload.")
    id: str | None = Field(
        default=None,
        description="Tool call ID this response corresponds to.",
    )


class BinaryPart(OmitNoneModel):
    """Inline binary content, carried base64-encoded.

    ``binary`` is canonical; the semantic conventions call this ``blob`` and
    name the media type ``mime_type``, so both spellings are accepted and
    ``media_type`` stays the field a reader can rely on.
    """

    type: Literal["binary", "blob"] = Field(
        default="binary",
        description="Part type discriminator. ``'binary'`` is canonical; ``'blob'`` is the semantic-convention spelling.",
    )
    content: str | None = Field(
        default=None, description="Base64-encoded content."
    )
    media_type: str | None = Field(
        default=None, description="IANA media type of the content."
    )
    mime_type: str | None = Field(
        default=None,
        description="Semantic-convention spelling of ``media_type``, accepted on read.",
    )
    modality: str | None = Field(
        default=None,
        description="Semantic-convention modality (``image``, ``audio``, ``video``, ``document``), when the writer supplied one.",
    )


class UrlPart(OmitNoneModel):
    """Content referenced by URL rather than carried inline.

    The modality lives in the type name here — ``image-url``, ``audio-url``,
    ``video-url``, ``document-url`` — which is how the platform writes it and
    how Pydantic AI models it. The semantic conventions instead use a single
    ``uri`` type carrying a separate ``modality``; that shape is accepted too,
    with ``uri`` read into ``url``.
    """

    type: Literal[
        "image-url", "audio-url", "video-url", "document-url", "uri"
    ] = Field(
        description="Part type discriminator; the four ``*-url`` names carry the modality, ``'uri'`` is the semantic-convention spelling."
    )
    url: str | None = Field(default=None, description="The referenced URL.")
    uri: str | None = Field(
        default=None,
        description="Semantic-convention spelling of ``url``, accepted on read.",
    )
    media_type: str | None = Field(default=None)
    mime_type: str | None = Field(default=None)
    modality: str | None = Field(
        default=None,
        description="Set only on a semantic-convention ``uri`` part, where the type name does not carry it.",
    )

    @property
    def target(self) -> str | None:
        """The referenced location under whichever spelling was written."""
        return self.url or self.uri


class FilePart(OmitNoneModel):
    """Content referenced by a provider-assigned file id (semconv ``file``)."""

    type: Literal["file"] = Field(default="file")
    file_id: str | None = Field(default=None)
    mime_type: str | None = Field(default=None)
    modality: str | None = Field(default=None)


class CompactionPart(OmitNoneModel):
    """A compaction marker — history summarized to fit a context window."""

    type: Literal["compaction"] = Field(default="compaction")
    content: str | None = Field(
        default=None,
        description="The summary that replaced the compacted turns.",
    )


class GenericPart(OmitNoneModel):
    """Any part type this SDK does not model.

    The catch-all is the important one. Before it, the union was strictly
    discriminated, so a single unmodelled part raised ``union_tag_invalid`` and
    took the **whole message** with it — a conversation containing one image was
    unparseable. An unknown part is not an error: the spec grows, and the
    platform can write a type this build has never heard of. It degrades to
    "some part, contents preserved" instead.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(description="The part type as written.")


#: Every `type` that maps onto a modelled part, including the semantic-
#: convention spellings we accept as aliases. Anything absent becomes a
#: `GenericPart`.
PART_MODEL_BY_TAG: dict[str, str] = {
    "text": "text",
    "thinking": "thinking",
    "reasoning": "thinking",
    "tool_call": "tool_call",
    "tool_call_response": "tool_call_response",
    "binary": "binary",
    "blob": "binary",
    "image-url": "url",
    "audio-url": "url",
    "video-url": "url",
    "document-url": "url",
    "uri": "url",
    "file": "file",
    "compaction": "compaction",
}


def _part_tag(value: Any) -> str:
    """Map a part's `type` onto the model that should parse it.

    Aliases collapse here — `thinking`/`reasoning` are one model, as are
    `binary`/`blob` and the five URL spellings — and anything unrecognized
    routes to `generic` rather than failing the message.
    """
    raw = (
        value.get("type")
        if isinstance(value, dict)
        else getattr(value, "type", None)
    )
    return (
        PART_MODEL_BY_TAG.get(raw, "generic")
        if isinstance(raw, str)
        else "generic"
    )


MessagePart = Annotated[
    Annotated[TextPart, Tag("text")]
    | Annotated[ThinkingPart, Tag("thinking")]
    | Annotated[ToolCallRequestPart, Tag("tool_call")]
    | Annotated[ToolCallResponsePart, Tag("tool_call_response")]
    | Annotated[BinaryPart, Tag("binary")]
    | Annotated[UrlPart, Tag("url")]
    | Annotated[FilePart, Tag("file")]
    | Annotated[CompactionPart, Tag("compaction")]
    | Annotated[GenericPart, Tag("generic")],
    Discriminator(_part_tag),
]
"""Every message part shape, tagged by `type`, with unknown types preserved."""


class InputMessage(OmitNoneModel):
    """Input message in OTel Gen AI semantic convention format."""

    role: Literal["system", "user", "assistant", "tool"] = Field(
        description="Message role: ``'system'``, ``'user'``, ``'assistant'``, or ``'tool'``.",
    )
    parts: list[MessagePart] = Field(
        description="Ordered list of content parts.",
    )
    name: str | None = Field(default=None, description="Optional sender name.")


class OutputMessage(OmitNoneModel):
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


class SystemInstruction(OmitNoneModel):
    """A single system instruction part (text content)."""

    type: Literal["text"] = Field(
        default="text",
        description="Part type discriminator, always ``'text'``.",
    )
    content: str = Field(description="The instruction text content.")


SystemInstructions = list[SystemInstruction]
"""List of :class:`SystemInstruction` instances."""


class ToolDefinition(OmitNoneModel):
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
