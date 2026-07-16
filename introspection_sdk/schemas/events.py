"""Pydantic mirrors of the DP read-only ``/v1/events`` surface.

Field names are kept on-the-wire (snake_case) to match the DP Pydantic
models verbatim. Every model sets ``extra="allow"`` so new server fields
don't break older clients.

``GET /v1/events`` is a single cursor-paginated list read over the
append-only ``otel_logs`` store. The ``grain`` query param selects one of
three projections, each with its own row model:

* ``raw`` (default) — one :class:`RawEvent` per event record.
* ``introspection.observation`` — resolved lens observations
  (:class:`LensObservation`).
* ``introspection.pattern`` — the current pattern catalog
  (:class:`PatternGrainEvent`).

All three share the standard cursor envelope
(:class:`~introspection_sdk.schemas.pagination.Paginated`) with an opaque
``next`` token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = [
    "EventGrain",
    "EventInclude",
    "EventRecord",
    "EventSortField",
    "LensObservation",
    "ObservationLens",
    "ObservationSeverity",
    "PatternGrainEvent",
    "RawEvent",
]

# --- Enumerated literals (mirror the DP StrEnums) -------------------

EventGrain = Literal[
    "raw", "introspection.observation", "introspection.pattern"
]
"""Readable projections exposed through ``GET /v1/events``."""

EventSortField = Literal["created"]
"""Allow-listed fields for event ordering."""

EventInclude = Literal["attributes", "body"]
"""Optional raw-event expansions, passed as a repeated ``include`` query
param on the events list route."""

ObservationLens = Literal[
    "user_intent",
    "task_resolution",
    "user_sentiment",
    "agent_struggle",
    "environment_issue",
]
"""Perspective used to extract an observation from a conversation."""

ObservationSeverity = Literal["low", "medium", "high"]
"""Severity of a lens observation."""


class _ApiModel(BaseModel):
    # ``extra="allow"`` keeps unknown server fields; ``protected_namespaces=()``
    # silences the ``model_`` warning for wire fields like ``model``.
    model_config = ConfigDict(extra="allow", protected_namespaces=())


class RawEvent(_ApiModel):
    """One raw event record from ``otel_logs`` (``grain=raw``)."""

    id: str
    timestamp: datetime
    trace_id: str | None = None
    span_id: str | None = None
    conversation_id: str | None = None
    event_name: str | None = None
    service_name: str | None = None
    environment: str | None = None
    runtime_group_id: UUID | None = None
    runtime_id: UUID | None = None
    experiment_id: UUID | None = None
    recipe_git_commit_sha: str | None = None
    body: str | None = None
    attributes: dict[str, Any] | None = None


class LensObservation(_ApiModel):
    """One lens observation (``grain=introspection.observation``).

    The resolved lens-observation projection over ``otel_logs``, current as
    of the queried window end, with its current pattern assignment.
    """

    id: UUID
    lens: ObservationLens
    label: str | None = None
    summary: str | None = None
    severity: ObservationSeverity | None = None
    confidence: float | None = None
    conversation_id: str | None = None
    service_name: str | None = None
    runtime_group_id: UUID | None = None
    runtime_id: UUID | None = None
    recipe_git_commit_sha: str | None = None
    experiment_id: UUID | None = None
    environment: str | None = None
    segment: int | None = None
    pattern_id: UUID | None = None
    assignment_score: float | None = None
    assignment_method: str | None = None
    metadata: dict[str, Any] | None = None
    resolution: str | None = None
    sentiment: str | None = None
    evidence_refs: list[str] | None = None
    prompt_version: str | None = None
    model: str | None = None
    source_hash: str | None = None
    replaces_observation_id: UUID | None = None
    observed_at: datetime


class PatternGrainEvent(_ApiModel):
    """Current pattern catalog row (``grain=introspection.pattern``)."""

    pattern_id: str
    name: str | None = None
    description: str | None = None
    lens: str | None = None
    runtime_group_id: UUID | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    replacement_pattern_id: str | None = None
    last_detected_at: datetime | None = None


#: Union of the three event grain row models. The DP list route returns one
#: of these per record depending on the requested ``grain``; the three models
#: have disjoint required fields, so the union routes each row unambiguously.
EventRecord = RawEvent | LensObservation | PatternGrainEvent
