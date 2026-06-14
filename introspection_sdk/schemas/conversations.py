"""Pydantic mirrors of the DP read-only ``/v1/conversations`` surface.

Field names are kept on-the-wire (snake_case) to match the DP Pydantic
models verbatim. Every model sets ``extra="allow"`` so new server fields
don't break older clients.

The surface uses two distinct paging styles:

* **Cursor paging** (``GET /v1/conversations``) — the standard
  Introspection :class:`~introspection_sdk.schemas.pagination.Paginated`
  envelope with an opaque ``next`` token.
* **After/has_more paging** (``GET /v1/conversations/{id}/items``) — an
  OpenAI-style :class:`ConversationItemList` envelope with ``first_id`` /
  ``last_id`` / ``has_more``. There is no ``next`` token: pass the
  previous page's ``last_id`` as the ``after`` query param while
  ``has_more`` is true.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from introspection_sdk.schemas.genai import (
    InputMessage,
    OutputMessage,
    SystemInstruction,
    ToolDefinition,
)

__all__ = [
    "ConversationItem",
    "ConversationItemInclude",
    "ConversationItemList",
    "ConversationItemNodeType",
    "ConversationResponse",
    "ConversationSummary",
    "IntrospectionMetadata",
    "SpanEvent",
    "SpanKind",
    "SpanStatus",
]

# --- Enumerated literals (mirror conversations.ts) ------------------

SpanStatus = Literal["Ok", "Error", "Unset"]
"""OpenTelemetry span status code values."""

SpanKind = Literal[
    "UNSPECIFIED",
    "INTERNAL",
    "SERVER",
    "CLIENT",
    "PRODUCER",
    "CONSUMER",
]
"""OpenTelemetry span kind values."""

ConversationItemNodeType = Literal["agent", "assistant", "tool_call", "span"]
"""Lightweight node type for conversation item trees."""

ConversationItemInclude = Literal[
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.system_instructions",
    "gen_ai.tool.definitions",
    "events",
    "resource_attributes",
    "span_attributes",
]
"""Optional conversation item expansions, passed as a repeated ``include``
query param on the items routes."""


class _ApiModel(BaseModel):
    # ``extra="allow"`` keeps unknown server fields; ``protected_namespaces=()``
    # silences the ``model_`` warning for wire fields like ``model_name``.
    model_config = ConfigDict(extra="allow", protected_namespaces=())


class IntrospectionMetadata(_ApiModel):
    """Introspection-specific metadata enriched during trace ingestion."""

    member_id: str | None = None
    is_new_conversation: bool | None = None
    conversation_position: int | None = None
    continuation_method: str | None = None
    history_hash_hit: bool | None = None
    new_messages_start: int | None = None
    new_messages_end: int | None = None
    client_message_id: str | None = None


class SpanEvent(_ApiModel):
    """An event within a span (exception, log message, state change, ...)."""

    timestamp: datetime
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class ConversationItem(_ApiModel):
    """Canonical conversation item resource — one span of a conversation.

    In the items LIST response, ``input_messages`` carries the turn-local
    delta (only the messages new to that turn). On the single-item GET,
    ``input_messages`` is the FULL input history supplied to that span.
    """

    object: Literal["conversation.item"] = "conversation.item"
    id: str
    type: Literal["span"] = "span"
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    created_at: datetime
    span_name: str
    span_kind: SpanKind
    node_type: ConversationItemNodeType
    operation_name: str | None = None
    status_code: SpanStatus | None = None
    status_message: str | None = None
    agent_name: str | None = None
    model_name: str | None = None
    request_model: str | None = None
    response_model: str | None = None
    response_id: str | None = None
    service_name: str | None = None
    provider_name: str | None = None
    duration_ns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_call_arguments: str | None = None
    tool_definitions: list[ToolDefinition] | None = None
    introspection: IntrospectionMetadata | None = None
    span_attributes: dict[str, Any] | None = None
    input_messages: list[InputMessage] = Field(default_factory=list)
    output_message: OutputMessage | None = None
    events: list[SpanEvent] | None = None
    resource_attributes: dict[str, Any] | None = None
    system_instructions: list[SystemInstruction] | None = None
    gen_ai_input_messages: list[InputMessage] | None = None
    gen_ai_output_messages: list[OutputMessage] | None = None


class ConversationItemList(_ApiModel):
    """OpenAI-style list envelope for conversation items.

    Unlike :class:`~introspection_sdk.schemas.pagination.Paginated`, there
    is no ``next`` token: page by passing ``last_id`` as the ``after``
    query param while ``has_more`` is true.
    """

    object: Literal["list"] = "list"
    data: list[ConversationItem] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class ConversationSummary(_ApiModel):
    """Summary of a conversation, aggregated from trace spans.

    Returned by ``GET /v1/conversations`` inside the standard cursor
    envelope ``Paginated[ConversationSummary]``.
    """

    trace_id: str
    conversation_id: str | None = None
    org_id: UUID
    project_id: UUID
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float
    service_name: str | None = None
    model: str | None = None
    response_model: str | None = None
    agent_name: str | None = None
    operation_name: str | None = None
    total_input_tokens: int
    total_output_tokens: int
    trace_count: int
    span_count: int
    status: SpanStatus
    has_errors: bool
    signal_categories: list[str] = Field(default_factory=list)
    input_messages: list[InputMessage] = Field(default_factory=list)
    output_messages: list[OutputMessage] = Field(default_factory=list)
    introspection: IntrospectionMetadata | None = None


class ConversationResponse(_ApiModel):
    """Responses-API-style view of a conversation — the full input
    history, output, system instructions, and tool definitions of the
    most recent LLM turn. Built client-side by ``Conversations.retrieve``
    from the single-item detail route.
    """

    conversation_id: str
    response_id: str | None = None
    item_id: str
    created_at: datetime
    model: str | None = None
    provider_name: str | None = None
    input_messages: list[InputMessage] = Field(default_factory=list)
    output_messages: list[OutputMessage] = Field(default_factory=list)
    system_instructions: list[SystemInstruction] | None = None
    tool_definitions: list[ToolDefinition] | None = None
