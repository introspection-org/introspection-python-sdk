"""The GenAI span returned by conversation item reads.

A conversation item **is** an OpenTelemetry span, so this models it as one:
identity and timing at the top level, everything else under ``attributes`` keyed
by its OpenTelemetry semantic-convention name. ``attributes.gen_ai.request.model``
is called that here because that is what the SDK wrote when it created the span.

- ``GET /v1/conversations/{id}/items`` — that turn's **delta**; concatenate in
  order for the transcript, each message appearing once.
- ``GET /v1/conversations/{id}/items/{item_id}`` — the **full history** as of
  that turn. This is the resumption read, and it needs no ``include``.

Full history is the detail read only because returning it per item on a list is
quadratic — turn 50 would carry fifty messages, turn 49 forty-nine, and so on.

**Absent means absent.** Nothing serializes as ``null``; a value that is not
present is a key that is not there. The typed families below are a convenience
over an open tree, not a closed set — every model allows extra keys, so an
attribute nobody modelled still arrives and still round-trips.

See ``docs/design/conversations-genai-representation.md`` in ``introspection-cloud``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from introspection_sdk.schemas.genai import (
    InputMessage,
    OutputMessage,
    SystemInstruction,
    ToolDefinition,
)

__all__ = [
    "GenAiAgent",
    "GenAiAttributes",
    "GenAiConversation",
    "GenAiInput",
    "GenAiOperation",
    "GenAiOutput",
    "GenAiProvider",
    "GenAiRequest",
    "GenAiResponse",
    "GenAiSpan",
    "GenAiSpanList",
    "GenAiTool",
    "GenAiToolCall",
    "GenAiCost",
    "GenAiUsage",
    "IntrospectionAttributes",
    "IntrospectionConversation",
    "IntrospectionRecipe",
    "IntrospectionRuntime",
    "SpanAttributes",
    "SpanKind",
    "SpanStatus",
    "SpanStatusCode",
    "TokenCount",
]

SpanStatusCode = Literal["Ok", "Error", "Unset"]
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


class _SpanModel(BaseModel):
    """Open, omit-empty base for every model on this surface.

    ``extra="allow"`` is not defensive boilerplate here — it is the contract.
    The server returns the attribute tree as stored rather than an allow-list,
    so a customer's own ``gen_ai.*`` or domain attribute arrives on a model that
    never declared it. Forbidding extras would reintroduce exactly the lossiness
    this representation exists to remove.

    ``protected_namespaces=()`` silences Pydantic's ``model_`` warning for wire
    fields like ``model``.
    """

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    @model_serializer(mode="wrap")
    def _omit_empty(self, handler: SerializerFunctionWrapHandler) -> Any:
        serialized = handler(self)
        if not isinstance(serialized, dict):
            return serialized
        # Drop None only. Empty containers are dropped by the fields that
        # default to them; a `0` or `""` that survived this far came from the
        # server and is a real value, not a placeholder.
        return {
            key: value
            for key, value in serialized.items()
            if value is not None
        }


# --- gen_ai.* -------------------------------------------------------------


class GenAiOperation(_SpanModel):
    """``gen_ai.operation.name`` — ``chat``, ``execute_tool``, ``invoke_agent``."""

    name: str | None = None


class GenAiProvider(_SpanModel):
    """``gen_ai.provider.name``. Replaced the older ``gen_ai.system``."""

    name: str | None = None


class GenAiConversation(_SpanModel):
    """``gen_ai.conversation.id``."""

    id: str | None = None


class GenAiAgent(_SpanModel):
    """``gen_ai.agent.*``."""

    id: str | None = None
    name: str | None = None
    description: str | None = None


class GenAiRequest(_SpanModel):
    """``gen_ai.request.*`` — what was asked for."""

    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    seed: int | None = None
    stream: bool | None = None


class GenAiResponse(_SpanModel):
    """``gen_ai.response.*`` — what came back."""

    id: str | None = None
    model: str | None = None
    finish_reasons: list[str] | None = None


class TokenCount(_SpanModel):
    """A nested token count, e.g. ``gen_ai.usage.cache_read.input_tokens``."""

    input_tokens: int | None = None


class GenAiUsage(_SpanModel):
    """``gen_ai.usage.*``.

    On an item these are that operation's usage. On a conversation summary they
    are the conversation's totals — same attribute, same honest meaning for its
    scope, disambiguated by which read the object came from.

    Cache tokens are standard: they were a local extension until the GenAI
    conventions adopted them.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read: TokenCount | None = None
    cache_creation: TokenCount | None = None


class GenAiToolCall(_SpanModel):
    """``gen_ai.tool.call.*``."""

    id: str | None = None
    arguments: str | None = None


class GenAiTool(_SpanModel):
    """``gen_ai.tool.*``."""

    name: str | None = None
    type: str | None = None
    description: str | None = None
    call: GenAiToolCall | None = None
    definitions: list[ToolDefinition] | None = None


class GenAiInput(_SpanModel):
    """``gen_ai.input.messages``.

    Full history on item detail; the turn-local delta on the items list.
    """

    messages: list[InputMessage] = Field(default_factory=list)


class GenAiOutput(_SpanModel):
    """``gen_ai.output.messages``."""

    messages: list[OutputMessage] = Field(default_factory=list)


class GenAiCost(_SpanModel):
    """``gen_ai.cost.usd``.

    Not part of the published semantic conventions, but this is the name the
    span is *written* with — the platform's ClickHouse cost column is
    materialized from ``gen_ai.cost.usd``, so the read returns the attribute
    under the name it was stored as rather than relocating it.

    Scoped by which read returned the span, the same way ``gen_ai.usage.*`` is:
    this operation's cost on an item, the conversation total on a summary.

    Distinct from ``introspection.llm.cost_usd``, which is the *provider*-
    reported figure (e.g. OpenRouter's ``usage.cost``) rather than the SDK's
    own calculation. Both can be present; they are different measurements.
    """

    usd: float | None = None


class GenAiAttributes(_SpanModel):
    """The ``gen_ai.*`` attribute family, nested as the convention names it."""

    operation: GenAiOperation | None = None
    provider: GenAiProvider | None = None
    conversation: GenAiConversation | None = None
    agent: GenAiAgent | None = None
    request: GenAiRequest | None = None
    response: GenAiResponse | None = None
    usage: GenAiUsage | None = None
    cost: GenAiCost | None = None
    tool: GenAiTool | None = None
    input: GenAiInput | None = None
    output: GenAiOutput | None = None
    system_instructions: list[SystemInstruction] | None = None


# --- introspection.* ------------------------------------------------------


class _Id(_SpanModel):
    """An ``{id}`` node — ``introspection.org.id`` and friends."""

    id: str | None = None


class IntrospectionRuntime(_SpanModel):
    """``introspection.runtime.*``.

    Two ids, not one: ``id`` is the specific runtime deployment, ``group_id``
    the stable group it belongs to. Typing this as a bare ``{id}`` node loses
    ``group_id`` to ``model_extra`` — silently, because the tree is open.
    """

    id: str | None = None
    group_id: str | None = None


class IntrospectionRecipe(_SpanModel):
    """``introspection.recipe.*``."""

    git_commit_sha: str | None = None


class IntrospectionConversation(_SpanModel):
    """``introspection.conversation.*``.

    These describe the turn's place in the conversation.
    """

    position: int | None = None
    is_new: bool | None = None
    continuation_method: str | None = None
    history_hash_hit: bool | None = None
    new_messages_start: int | None = None
    new_messages_end: int | None = None
    client_message_id: str | None = None
    trace_count: int | None = None
    span_count: int | None = None
    tool_use_count: int | None = None
    failed_tool_use_count: int | None = None
    has_errors: bool | None = None


class IntrospectionAttributes(_SpanModel):
    """The ``introspection.*`` attribute family.

    Everything here is ours.
    """

    org: _Id | None = None
    project: _Id | None = None
    member: _Id | None = None
    run: _Id | None = None
    task: _Id | None = None
    runtime: IntrospectionRuntime | None = None
    experiment: _Id | None = None
    environment: str | None = None
    conversation: IntrospectionConversation | None = None
    recipe: IntrospectionRecipe | None = None


# --- the span -------------------------------------------------------------


class SpanAttributes(_SpanModel):
    """The span's attribute tree.

    Typed for the two families we own the meaning of; open for everything
    else, so a customer attribute survives the round trip.
    """

    gen_ai: GenAiAttributes | None = None
    introspection: IntrospectionAttributes | None = None


class SpanStatus(_SpanModel):
    """OpenTelemetry span status."""

    code: SpanStatusCode | None = None
    message: str | None = None


class GenAiSpan(_SpanModel):
    """One conversation item, or one conversation summary.

    Same type either way — see the module docstring for what differs.
    """

    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    name: str | None = None
    kind: SpanKind | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_ns: int | None = None
    status: SpanStatus | None = None
    resource: dict[str, Any] | None = None
    attributes: SpanAttributes = Field(default_factory=SpanAttributes)

    @property
    def conversation_id(self) -> str | None:
        """``attributes.gen_ai.conversation.id``, if present."""
        gen_ai = self.attributes.gen_ai
        return (
            gen_ai.conversation.id if gen_ai and gen_ai.conversation else None
        )

    @property
    def model(self) -> str | None:
        """The model this span ran against — requested, else responded.

        The old flat shape exposed this as a server-side ``coalesce()`` named
        ``model_name``, which existed in no specification. Same precedence,
        now visibly the client's choice rather than a field the API invents.
        """
        gen_ai = self.attributes.gen_ai
        if gen_ai is None:
            return None
        requested = gen_ai.request.model if gen_ai.request else None
        return requested or (
            gen_ai.response.model if gen_ai.response else None
        )

    @property
    def input_messages(self) -> list[InputMessage]:
        """``attributes.gen_ai.input.messages`` — empty rather than absent.

        A convenience for the common read. Reaching four levels down to answer
        "what was said" is the one place this shape is worse than the flat one,
        so the accessor pays that cost once here instead of at every call site.
        """
        gen_ai = self.attributes.gen_ai
        return list(gen_ai.input.messages) if gen_ai and gen_ai.input else []

    @property
    def output_messages(self) -> list[OutputMessage]:
        """``attributes.gen_ai.output.messages`` — empty rather than absent."""
        gen_ai = self.attributes.gen_ai
        return list(gen_ai.output.messages) if gen_ai and gen_ai.output else []


class GenAiSpanList(_SpanModel):
    """The ``/v1/conversations/{id}/items`` envelope.

    ``first_id`` and ``last_id`` are informational; pagination uses the opaque
    ``next`` cursor.
    """

    object: Literal["list"] = "list"
    data: list[GenAiSpan] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False
    next: str | None = None
