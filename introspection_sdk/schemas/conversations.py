"""Conversation resources and query vocabulary for ``/v1/conversations``.

The message-family ``include`` values are gone. The items read returns the
full message history by default, so there is nothing for them to gate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from introspection_sdk.schemas.genai import OmitNoneModel

__all__ = [
    "Conversation",
    "ConversationAgent",
    "ConversationCost",
    "ConversationExperiment",
    "ConversationItemInclude",
    "ConversationMetrics",
    "ConversationOwner",
    "ConversationRecipe",
    "ConversationRuntime",
    "ConversationSortField",
    "ConversationUsage",
    "SpanKind",
    "SpanStatus",
]


class ConversationAgent(OmitNoneModel):
    id: str
    name: str | None = None
    parent_id: str | None = None
    invocation_id: str | None = None
    depth: int | None = None


class ConversationUsage(OmitNoneModel):
    """Token totals across the conversation.

    ``total_input_tokens`` counts uncached input plus cache reads and writes,
    so it is not the sum of the items' ``gen_ai.usage.input_tokens``.
    """

    total_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ConversationCost(OmitNoneModel):
    usd: float = 0.0


class ConversationMetrics(OmitNoneModel):
    duration_ms: float = 0.0
    trace_count: int = 0
    max_turn: int | None = None
    span_count: int = 0
    tool_use_count: int = 0
    failed_tool_use_count: int = 0
    llm_call_count: int = 0
    failed_llm_call_count: int = 0
    has_errors: bool = False


class ConversationRuntime(OmitNoneModel):
    id: UUID | None = None
    group_id: UUID | None = None


class ConversationExperiment(OmitNoneModel):
    id: UUID | None = None


class ConversationRecipe(OmitNoneModel):
    git_commit_sha: str | None = None


class ConversationOwner(OmitNoneModel):
    key: str | None = None


class Conversation(OmitNoneModel):
    object: Literal["conversation"] = "conversation"
    id: str
    task_title: str | None = None
    created_at: datetime
    updated_at: datetime
    agents: list[ConversationAgent] | None = None
    usage: ConversationUsage = Field(default_factory=ConversationUsage)
    cost: ConversationCost = Field(default_factory=ConversationCost)
    metrics: ConversationMetrics = Field(default_factory=ConversationMetrics)
    environment: str | None = None
    service_name: str | None = None
    runtime: ConversationRuntime | None = None
    experiment: ConversationExperiment | None = None
    recipe: ConversationRecipe | None = None
    owner: ConversationOwner | None = None
    metadata: dict[str, str] | None = None


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


ConversationSortField = Literal[
    "created", "duration", "turns", "tokens", "cost"
]
"""Allow-listed summary fields for ``GET /v1/conversations`` sorting."""

ConversationItemInclude = Literal[
    "gen_ai.system_instructions",
    "gen_ai.tool.definitions",
    "events",
    "span_attributes",
    "resource_attributes",
]
"""Optional conversation item expansions, passed as a repeated ``include``
query param on the items routes."""
