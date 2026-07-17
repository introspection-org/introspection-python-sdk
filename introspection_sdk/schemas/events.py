"""Pydantic mirrors of the DP read-only ``/v1/events`` surface.

Field names are kept on-the-wire (snake_case) to match the DP Pydantic
models verbatim. Every model sets ``extra="allow"`` so new server fields
don't break older clients.

``GET /v1/events`` is a single cursor-paginated list read over the
append-only ``otel_logs`` store. Every list read names its family — the
``event_name`` query param is **required, exactly one** — so a response
is always homogeneous. Each row is one member of the discriminated
:data:`Event` union: a common :class:`IntrospectionEventBase` envelope
plus a nested typed ``payload`` fixed by the family.

All reads share the standard cursor envelope
(:class:`~introspection_sdk.schemas.pagination.Paginated`) with an opaque
``next`` token.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ClusteringRunEvent",
    "ClusteringRunPayload",
    "Event",
    "EventSortField",
    "FeedbackEvent",
    "FeedbackPayload",
    "IntrospectionEventBase",
    "IntrospectionEventName",
    "JudgementEvent",
    "JudgementPayload",
    "KNOWN_EVENT_NAMES",
    "ObservationEvent",
    "ObservationLens",
    "ObservationPayload",
    "ObservationSeverity",
    "PatternAssignmentEvent",
    "PatternAssignmentPayload",
    "PatternEvent",
    "PatternPayload",
]


class IntrospectionEventName(StrEnum):
    """The six canonical platform event families — a closed, typed set.

    Legacy verb-suffixed names on stored rows are normalized server-side;
    responses always carry the canonical family name.
    """

    FEEDBACK = "introspection.feedback"
    OBSERVATION = "introspection.observation"
    OBSERVATION_CLUSTERING_RUN = "introspection.observation_clustering.run"
    JUDGEMENT = "introspection.judgement"
    PATTERN = "introspection.pattern"
    PATTERN_ASSIGNMENT = "introspection.pattern.assignment"


#: Wire values of every family in the closed set, for cheap membership
#: checks before discriminated validation.
KNOWN_EVENT_NAMES: frozenset[str] = frozenset(
    member.value for member in IntrospectionEventName
)

EventSortField = Literal[
    "timestamp",
    "observed_at",
    "created_at",
    "updated_at",
    "last_detected_at",
]
"""Allow-listed sort fields; validity is per family (server-validated).

Observation reads sort by ``observed_at`` (default); pattern reads by
``updated_at`` (default), ``created_at``, or ``last_detected_at``; the
stream families (feedback, judgement, assignment, clustering-run) sort by
``timestamp`` (default)."""

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


class IntrospectionEventBase(_ApiModel):
    """Common event envelope — the queryable surface, shared by every
    family. ``org``/``project`` are never serialized: tenant scope is
    implied by the runner's JWT."""

    id: str
    timestamp: datetime
    event_name: str
    trace_id: str | None = None
    span_id: str | None = None
    conversation_id: str | None = None
    service_name: str | None = None
    environment: str | None = None
    runtime_group_id: UUID | None = None
    runtime_id: UUID | None = None
    experiment_id: UUID | None = None
    recipe_git_commit_sha: str | None = None


# --- payload models: pure family detail, no envelope duplication -----


class ObservationPayload(_ApiModel):
    """One resolved observation — supersession applied, with its current
    pattern assignment (the server-side fold)."""

    observation_id: UUID
    lens: ObservationLens
    label: str | None = None
    summary: str | None = None
    severity: ObservationSeverity | None = None
    confidence: float | None = None
    segment: int | None = None
    sentiment: str | None = None
    resolution: str | None = None
    evidence_refs: list[str] | None = None
    prompt_version: str | None = None
    model: str | None = None
    source_hash: str | None = None
    replaces_observation_id: UUID | None = None
    pattern_id: str | None = None
    assignment_score: float | None = None
    assignment_method: str | None = None
    metadata: dict[str, Any] | None = None


class PatternPayload(_ApiModel):
    """One folded pattern catalog row — the pattern as it currently is."""

    pattern_id: str
    action: str | None = None
    name: str | None = None
    description: str | None = None
    lens: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    last_detected_at: datetime | None = None
    reason: str | None = None
    replacement_pattern_id: str | None = None
    derived_from_pattern_id: str | None = None
    run_id: str | None = None


class PatternAssignmentPayload(_ApiModel):
    """One observation-to-pattern assignment event.

    ``pattern_id`` is ``None`` when the observation was explicitly
    unassigned; ``observation_id`` alone is the row identity.
    """

    observation_id: UUID
    pattern_id: str | None = None
    method: str | None = None
    run_id: str | None = None
    score: float | None = None


class ClusteringRunPayload(_ApiModel):
    """One observation-clustering run completion event."""

    run_id: str
    lens: str | None = None
    status: str | None = None
    trigger: str | None = None
    observation_count: int | None = None
    pattern_count: int | None = None
    noise_count: int | None = None
    params: dict[str, Any] | None = None
    replaces_run_id: str | None = None
    error: str | None = None


class FeedbackPayload(_ApiModel):
    """One end-user feedback event, as emitted by the SDK ``feedback()``
    surfaces."""

    name: str
    comments: str | None = None
    value: float | None = None
    user_id: str | None = None
    anonymous_id: str | None = None
    sentiment: str | None = None
    #: gen_ai.request.previous_response_id — response the feedback anchors to.
    previous_response_id: str | None = None
    agent_name: str | None = None  #: gen_ai.agent.name
    agent_id: str | None = None  #: gen_ai.agent.id
    properties: dict[str, Any] | None = None


class JudgementPayload(_ApiModel):
    """One judge evaluation result event."""

    judgement_id: str
    judge_id: str | None = None
    result: str | None = None
    definition_hash: str | None = None
    contract_version: str | None = None
    sequence_hash: str | None = None
    experiment_arm_id: UUID | None = None


# --- whole-event models: envelope + typed payload, Literal tag -------


class ObservationEvent(IntrospectionEventBase):
    """A resolved observation (``event_name=introspection.observation``)."""

    event_name: Literal[IntrospectionEventName.OBSERVATION]
    payload: ObservationPayload


class PatternEvent(IntrospectionEventBase):
    """A folded pattern catalog row (``event_name=introspection.pattern``)."""

    event_name: Literal[IntrospectionEventName.PATTERN]
    payload: PatternPayload


class PatternAssignmentEvent(IntrospectionEventBase):
    """A pattern assignment (``event_name=introspection.pattern.assignment``)."""

    event_name: Literal[IntrospectionEventName.PATTERN_ASSIGNMENT]
    payload: PatternAssignmentPayload


class ClusteringRunEvent(IntrospectionEventBase):
    """A clustering run
    (``event_name=introspection.observation_clustering.run``)."""

    event_name: Literal[IntrospectionEventName.OBSERVATION_CLUSTERING_RUN]
    payload: ClusteringRunPayload


class FeedbackEvent(IntrospectionEventBase):
    """An end-user feedback event (``event_name=introspection.feedback``)."""

    event_name: Literal[IntrospectionEventName.FEEDBACK]
    payload: FeedbackPayload


class JudgementEvent(IntrospectionEventBase):
    """A judge evaluation (``event_name=introspection.judgement``)."""

    event_name: Literal[IntrospectionEventName.JUDGEMENT]
    payload: JudgementPayload


#: The discriminated union of the six canonical event families. Pydantic
#: selects the member from the top-level ``event_name`` tag; the member
#: fixes the ``payload`` type.
Event = Annotated[
    ObservationEvent
    | PatternEvent
    | PatternAssignmentEvent
    | ClusteringRunEvent
    | FeedbackEvent
    | JudgementEvent,
    Field(discriminator="event_name"),
]
