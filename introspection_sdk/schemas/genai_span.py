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
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

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
    "ConversationCompaction",
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
    "IntrospectionAgent",
    "IntrospectionAttributes",
    "IntrospectionContains",
    "IntrospectionHistory",
    "IntrospectionIngest",
    "IntrospectionInvocation",
    "IntrospectionNewMessages",
    "IntrospectionRecipe",
    "IntrospectionRun",
    "IntrospectionRuntime",
    "IntrospectionTask",
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


class SpanModel(BaseModel):
    """Open, omit-empty base for every model on this surface.

    ``extra="allow"`` is not defensive boilerplate here — it is the contract.
    The server returns the attribute tree as stored rather than an allow-list,
    so a customer's own ``gen_ai.*`` or domain attribute arrives on a model that
    never declared it. Forbidding extras would reintroduce exactly the lossiness
    this representation exists to remove.

    A subclass that sets ``open_schema = True`` is open in strict mode too
    (``INTROSPECTION_STRICT_SCHEMA=1``): the ``gen_ai.*`` nodes and the
    attribute tree itself, whose keys the GenAI conventions and providers keep
    adding to. ``introspection.*`` and the span's own fields are the server's,
    so a key there the SDK does not model is API drift, which strict mode
    reports.

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


class GenAiOperation(SpanModel):
    """``gen_ai.operation.name`` — ``chat``, ``execute_tool``, ``invoke_agent``."""

    open_schema: ClassVar[bool] = True

    name: str | None = None


class GenAiProvider(SpanModel):
    """``gen_ai.provider.name``. Replaced the older ``gen_ai.system``."""

    open_schema: ClassVar[bool] = True

    name: str | None = None


class GenAiConversation(SpanModel):
    """``gen_ai.conversation.id``."""

    open_schema: ClassVar[bool] = True

    id: str | None = None


class GenAiAgent(SpanModel):
    """``gen_ai.agent.*``."""

    open_schema: ClassVar[bool] = True

    id: str | None = None
    name: str | None = None
    description: str | None = None


class GenAiRequest(SpanModel):
    """``gen_ai.request.*`` — what was asked for."""

    open_schema: ClassVar[bool] = True

    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    seed: int | None = None
    stream: bool | None = None


class GenAiResponse(SpanModel):
    """``gen_ai.response.*`` — what came back."""

    open_schema: ClassVar[bool] = True

    id: str | None = None
    model: str | None = None
    finish_reasons: list[str] | None = None


class TokenCount(SpanModel):
    """A nested token count, e.g. ``gen_ai.usage.cache_read.input_tokens``."""

    open_schema: ClassVar[bool] = True

    input_tokens: int | None = None


class GenAiUsage(SpanModel):
    """``gen_ai.usage.*``.

    On an item these are that operation's usage. On a conversation summary they
    are the conversation's totals — same attribute, same honest meaning for its
    scope, disambiguated by which read the object came from.

    Cache tokens are standard: they were a local extension until the GenAI
    conventions adopted them.
    """

    open_schema: ClassVar[bool] = True

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read: TokenCount | None = None
    cache_creation: TokenCount | None = None


class GenAiToolCall(SpanModel):
    """``gen_ai.tool.call.*``."""

    open_schema: ClassVar[bool] = True

    id: str | None = None
    arguments: str | None = None
    result: Any = None


class GenAiTool(SpanModel):
    """``gen_ai.tool.*``."""

    open_schema: ClassVar[bool] = True

    name: str | None = None
    type: str | None = None
    description: str | None = None
    call: GenAiToolCall | None = None
    definitions: list[ToolDefinition] | None = None


class GenAiInput(SpanModel):
    """``gen_ai.input.messages``.

    Full history on item detail; the turn-local delta on the items list.
    """

    open_schema: ClassVar[bool] = True

    messages: list[InputMessage] = Field(default_factory=list)


class GenAiOutput(SpanModel):
    """``gen_ai.output.messages``."""

    open_schema: ClassVar[bool] = True

    messages: list[OutputMessage] = Field(default_factory=list)


class GenAiCost(SpanModel):
    """``gen_ai.cost.usd``.

    Not part of the published semantic conventions, but this is the name the
    span is *written* with — the platform's cost column is derived from
    ``gen_ai.cost.usd``, so the read returns the attribute under the name it
    was stored as rather than relocating it.

    Scoped by which read returned the span, the same way ``gen_ai.usage.*`` is:
    this operation's cost on an item, the conversation total on a summary.

    Distinct from ``introspection.llm.cost_usd``, which is the *provider*-
    reported figure (e.g. OpenRouter's ``usage.cost``) rather than the SDK's
    own calculation. Both can be present; they are different measurements.
    """

    open_schema: ClassVar[bool] = True

    usd: float | None = None


class GenAiAttributes(SpanModel):
    """The ``gen_ai.*`` attribute family, nested as the convention names it."""

    open_schema: ClassVar[bool] = True

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


class IdNode(SpanModel):
    """An ``{id}`` node — ``introspection.org.id`` and friends."""

    id: str | None = None


class IntrospectionRun(IdNode):
    """``introspection.run.*``."""

    root_id: str | None = None
    """The run at the root of a chain of delegated runs."""
    parent_id: str | None = None


class IntrospectionTask(IdNode):
    """``introspection.task.*``."""

    run_id: str | None = None


class IntrospectionAgent(SpanModel):
    """``introspection.agent.*``: which agent in a runtime's agent tree made
    the call."""

    kind: str | None = None
    """``session`` for the top-level agent."""
    depth: str | None = None
    """Nesting depth, ``"0"`` at the top. A string: it travels as baggage."""
    parent_id: str | None = None
    invocation_id: str | None = None
    invocation_index: int | None = None


class IntrospectionInvocation(SpanModel):
    """``introspection.invocation.*``."""

    kind: str | None = None
    """``turn`` for a span that wraps one turn of the agent loop."""


class IntrospectionIngest(SpanModel):
    """``introspection.ingest.*``: the processor that handled the span."""

    host: str | None = None
    """Processor pod name."""
    ip: str | None = None
    """Processor pod IP."""
    node: str | None = None
    """Node the pod runs on."""
    time: int | None = None
    """When the processor handled the span's batch, microseconds since the
    epoch."""


class IntrospectionRuntime(SpanModel):
    """``introspection.runtime.*``.

    Two ids, not one: ``id`` is the specific runtime deployment, ``group_id``
    the stable group it belongs to. Typing this as a bare ``{id}`` node loses
    ``group_id`` to ``model_extra`` — silently, because the tree is open.
    """

    id: str | None = None
    group_id: str | None = None


class IntrospectionRecipe(SpanModel):
    """``introspection.recipe.*``."""

    git_commit_sha: str | None = None


class IntrospectionNewMessages(SpanModel):
    """``introspection.history.new_messages.*``: the half-open range of this
    call's input messages that were new to the conversation."""

    start: int | None = None
    end: int | None = None


class IntrospectionHistory(SpanModel):
    """``introspection.history.*``: where this model call sits in the
    conversation's message history, as the processor's linker inferred it.

    Absent on spans the linker never placed, such as tool and API calls.
    ``position`` is 1-based.
    """

    position: int | None = None
    is_new: bool | None = None
    continuation_method: str | None = None
    hash_hit: bool | None = None
    new_messages: IntrospectionNewMessages | None = None


class IntrospectionContains(SpanModel):
    """``introspection.contains.*``: what a chat span's sealed input delta and
    output contain.

    Stamped at ingest so a read can select rows without opening them.
    ``values`` are the ``contains=`` filter values the span answers, spelled
    exactly as a client passes them to ``items.list(contains=...)``, such as
    ``"gen_ai.input.messages.role:user"`` or
    ``"gen_ai.output.messages.parts.name:<tool>"``. A name list cut at the
    processor's bound carries ``"<path>:*"``. Paths and names only, never
    content. ``version`` is 0 or absent on a span that was never summarized.
    """

    version: int | None = None
    values: list[str] | None = None


class IntrospectionAttributes(SpanModel):
    """The ``introspection.*`` attribute family.

    Everything here is ours.
    """

    org: IdNode | None = None
    project: IdNode | None = None
    member: IdNode | None = None
    run: IntrospectionRun | None = None
    task: IntrospectionTask | None = None
    runtime: IntrospectionRuntime | None = None
    experiment: IdNode | None = None
    environment: str | None = None
    turn: int | None = None
    history: IntrospectionHistory | None = None
    recipe: IntrospectionRecipe | None = None
    contains: IntrospectionContains | None = None
    tool_response_ids: list[str] | None = None
    """``introspection.tool_response_ids``: the id of each tool response in a
    chat span's input delta, which is the id of the tool call it answers.
    Stamped from contains version 2; a list the processor cut at its bound
    ends in ``*``."""
    tool_call_ids: list[str] | None = None
    """``introspection.tool_call_ids``: the id of each tool call a chat span's
    output requests. Stamped from contains version 2; a list the processor
    cut at its bound ends in ``*``."""
    agent: IntrospectionAgent | None = None
    invocation: IntrospectionInvocation | None = None
    ingest: IntrospectionIngest | None = None
    byok: bool | None = None
    """Whether the call used the customer's own provider key."""
    termination_reason: str | None = None
    """Why the agent loop ended (``completed``, ...)."""


# --- the span -------------------------------------------------------------


class SpanAttributes(SpanModel):
    """The span's attribute tree.

    Typed for the two families we own the meaning of; open for everything
    else, so a customer attribute survives the round trip.
    """

    open_schema: ClassVar[bool] = True

    gen_ai: GenAiAttributes | None = None
    introspection: IntrospectionAttributes | None = None


class SpanStatus(SpanModel):
    """OpenTelemetry span status."""

    code: SpanStatusCode | str | None = None
    message: str | None = None


class GenAiSpan(SpanModel):
    """One conversation item, or one conversation summary.

    Same type either way — see the module docstring for what differs.
    """

    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    name: str | None = None
    kind: SpanKind | str | None = None
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


class ConversationCompaction(SpanModel):
    """The compaction anchor an items read started from."""

    applied: bool = False
    """``False`` when no compaction anchor resolved and the read started at
    the beginning of the conversation."""
    response_id: str | None = None
    """The response id the compaction anchor names."""
    cursor: str | None = None
    """Opaque cursor positioned at the anchor item."""
    history: list[dict[str, Any]] = Field(default_factory=list)
    """Recorded compactions, oldest first: each ``response_id`` with its
    ``at_compaction`` and ``since_compaction`` counts."""


class GenAiSpanList(SpanModel):
    """The ``/v1/conversations/{id}/items`` envelope.

    ``first_id`` and ``last_id`` are informational; pagination uses the opaque
    ``next`` cursor.
    """

    object: Literal["list"] = "list"
    data: list[GenAiSpan] = Field(default_factory=list)
    compaction: ConversationCompaction | None = None
    """Where an items read started when it began at the compaction anchor;
    absent on a read that did not ask for it."""
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False
    next: str | None = None
