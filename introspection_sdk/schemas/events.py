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

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

from introspection_sdk.schemas.routines import (
    OpenSkipReason,
    OpenTriggerType,
)

__all__ = [
    "AnnotationEvent",
    "AnnotationPayload",
    "RoutineSkippedEvent",
    "RoutineSkippedPayload",
    "RoutineTriggeredEvent",
    "RoutineTriggeredPayload",
    "ClusteringRunEvent",
    "ClusteringRunPayload",
    "Event",
    "EventSortField",
    "FeedbackEvent",
    "FeedbackPayload",
    "IntrospectionEventBase",
    "IntrospectionEventName",
    "IssueActivityBasePayload",
    "IssueActivityEvent",
    "IssueActivityPayload",
    "IssueCommentedPayload",
    "IssueCreatedPayload",
    "IssueDeletedPayload",
    "IssueEventAction",
    "IssueFieldChange",
    "IssueUpdatedPayload",
    "JudgeType",
    "JudgementBasePayload",
    "JudgementEgressPayload",
    "JudgementEvent",
    "JudgementPayload",
    "JudgementVerdictPayload",
    "KNOWN_EVENT_NAMES",
    "ObservationEvent",
    "ObservationLens",
    "ObservationPayload",
    "ObservationSeverity",
    "PatternAssignmentEvent",
    "PatternAssignmentPayload",
    "PatternEvent",
    "PatternPayload",
    "TrackEvent",
    "TrackPayload",
    "UnknownEvent",
    "UnknownIssuePayload",
    "UnknownJudgementPayload",
]


class IntrospectionEventName(StrEnum):
    """The platform event families this SDK types — a closed set.

    Legacy verb-suffixed names on stored rows are normalized server-side;
    responses always carry the canonical family name.
    """

    ANNOTATION = "introspection.annotation"
    FEEDBACK = "introspection.feedback"
    OBSERVATION = "introspection.observation"
    OBSERVATION_CLUSTERING_RUN = "introspection.observation_clustering.run"
    JUDGEMENT = "introspection.judgement"
    ISSUE = "introspection.issue"
    PATTERN = "introspection.pattern"
    PATTERN_ASSIGNMENT = "introspection.pattern.assignment"
    ROUTINE_TRIGGERED = "introspection.routines.triggered"
    ROUTINE_SKIPPED = "introspection.routines.skipped"
    """Project-owned: readable only with project-wide telemetry access."""
    TRACK = "introspection.track"
    """Virtual projection over app events from ``log_event`` / ``track``."""


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


class JudgeType(StrEnum):
    """Where a judge runs: on live traffic, on a dataset, or on a mission."""

    ONLINE = "online"
    OFFLINE = "offline"
    MISSION = "mission"


# A known value decodes to the member and an unknown one stays a ``str``, so a
# value the API adds later still decodes.
OpenJudgeType = Annotated[JudgeType | str, Field(union_mode="left_to_right")]


class _ApiModel(BaseModel):
    # ``extra="allow"`` keeps unknown server fields; ``protected_namespaces=()``
    # silences the ``model_`` warning for wire fields like ``model``.
    model_config = ConfigDict(extra="allow", protected_namespaces=())


def tag_or_unknown(field: str, known: frozenset[str]) -> Callable[[Any], str]:
    """A union discriminator on ``field``: a value outside ``known`` selects
    the union's ``unknown`` member, so a member the API adds later decodes."""

    def tag(payload: Any) -> str:
        if isinstance(payload, dict):
            value = payload.get(field)
        else:
            value = getattr(payload, field, None)
        return value if value in known else "unknown"

    return tag


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


class TrackPayload(_ApiModel):
    """One app event emitted through ``log_event`` / ``track``."""

    #: The custom ``event.name`` the caller logged, e.g. ``"ark.feed.entry"``.
    name: str
    #: The event's ``properties.*`` attributes, prefix stripped.
    properties: dict[str, Any] | None = None


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
    #: The authenticated member who authored the feedback.
    author_member_id: UUID | None = None


class AnnotationPayload(_ApiModel):
    """One member-authored annotation mutation."""

    member_id: UUID
    #: The member that ran the request for ``member_id``, e.g. an agent.
    actor_member_id: UUID | None = None
    actor_member_type: str | None = None
    labels: list[str] | None = None
    comment: str | None = None
    assignee_member_ids: list[UUID] | None = None


class JudgementBasePayload(_ApiModel):
    """What every judgement carries, whichever kind it is."""

    judgement_id: str
    judge_id: str | None = None
    judge_slug: str | None = None
    judge_type: OpenJudgeType | None = None
    runtime_slug: str | None = None
    result: str | None = None
    #: The execution outcome (``ok`` / ``error``), distinct from ``result``.
    status: str | None = None
    error_class: str | None = None
    error_message: str | None = None
    source_component: str | None = None
    judge_model: str | None = None
    experiment_arm_id: UUID | None = None


class JudgementVerdictPayload(JudgementBasePayload):
    """A recipe judge's verdict on a conversation."""

    kind: Literal["verdict"]
    reasoning: str | None = None
    definition_hash: str | None = None
    engine_version: str | None = None
    judge_provider: str | None = None
    contract_version: str | None = None
    sequence_hash: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class JudgementEgressPayload(JudgementBasePayload):
    """The egress policy gate's decision on one outbound request."""

    kind: Literal["egress"]
    #: Each answered question's probability of true, 0-100.
    scores: dict[str, int] | None = None
    questions: dict[str, str] | None = None
    policy_id: str | None = None
    policy_action: str | None = None
    reason: str | None = None
    request_host: str | None = None
    request_method: str | None = None
    request_path: str | None = None


class UnknownJudgementPayload(JudgementBasePayload):
    """Fallback for a judgement ``kind`` this SDK version predates: the
    shared fields are typed and the kind's own are kept as extras."""

    kind: str


JudgementPayload = Annotated[
    Annotated[JudgementVerdictPayload, Tag("verdict")]
    | Annotated[JudgementEgressPayload, Tag("egress")]
    | Annotated[UnknownJudgementPayload, Tag("unknown")],
    Discriminator(tag_or_unknown("kind", frozenset({"verdict", "egress"}))),
]
"""One judgement, discriminated by its ``kind`` (``verdict`` or ``egress``)."""


class IssueEventAction(StrEnum):
    """What an ``introspection.issue`` event records."""

    CREATED = "created"
    UPDATED = "updated"
    COMMENTED = "commented"
    DELETED = "deleted"


class IssueFieldChange(_ApiModel):
    """One authored field's value on either side of an update. A side that
    was empty is absent."""

    before: Any = None
    after: Any = None


class IssueActivityBasePayload(_ApiModel):
    """What every issue event carries, whichever action it records."""

    issue_id: UUID
    #: Revision of the issue the action wrote.
    revision: int | None = None
    #: The member who made the change or comment.
    member_id: UUID | None = None
    #: The member acting for ``member_id``, when the write was delegated.
    actor_member_id: UUID | None = None
    actor_member_type: str | None = None


class IssueCreatedPayload(IssueActivityBasePayload):
    action: Literal[IssueEventAction.CREATED]
    #: The authored fields the issue was created with.
    data: dict[str, Any]


class IssueUpdatedPayload(IssueActivityBasePayload):
    action: Literal[IssueEventAction.UPDATED]
    #: Each changed field, by name; ``members`` holds the people on the
    #: issue before and after.
    changes: dict[str, IssueFieldChange]


class IssueCommentedPayload(IssueActivityBasePayload):
    """A comment. Its author is ``member_id``; its time is the event's."""

    action: Literal[IssueEventAction.COMMENTED]
    comment: str


class IssueDeletedPayload(IssueActivityBasePayload):
    action: Literal[IssueEventAction.DELETED]


class UnknownIssuePayload(IssueActivityBasePayload):
    """Fallback for an issue ``action`` this SDK version predates: the
    shared fields are typed and the action's own are kept as extras."""

    action: str


IssueActivityPayload = Annotated[
    Annotated[IssueCreatedPayload, Tag(IssueEventAction.CREATED)]
    | Annotated[IssueUpdatedPayload, Tag(IssueEventAction.UPDATED)]
    | Annotated[IssueCommentedPayload, Tag(IssueEventAction.COMMENTED)]
    | Annotated[IssueDeletedPayload, Tag(IssueEventAction.DELETED)]
    | Annotated[UnknownIssuePayload, Tag("unknown")],
    Discriminator(
        tag_or_unknown(
            "action", frozenset(action.value for action in IssueEventAction)
        )
    ),
]
"""One issue event, discriminated by its ``action``."""


class RoutineTriggeredPayload(_ApiModel):
    """One routine trigger that ran.

    ``slot`` is the ``next_trigger_at`` a scheduled trigger claimed
    (``None`` for a hand trigger). ``posted`` says whether the prompt went
    into an existing task rather than a new one. ``member_id`` is the
    task's member, who owns the event; ``triggered_by_member_id`` is the
    person who triggered it by hand.
    """

    routine_id: UUID
    routine_name: str
    trigger_type: OpenTriggerType
    task_id: UUID
    """The task created, or posted into when ``posted`` is true."""
    posted: bool
    member_id: UUID
    prompt: str | None = None
    slot: datetime | None = None
    runtime_group_id: UUID | None = None
    triggered_by_member_id: UUID | None = None


class RoutineSkippedPayload(_ApiModel):
    """One scheduled routine trigger that ran nothing.

    Project-owned, so it names no member. ``task_id`` is set only when the
    routine targets an existing task.
    """

    routine_id: UUID
    trigger_type: OpenTriggerType
    reason: OpenSkipReason
    slot: datetime | None = None
    task_id: UUID | None = None


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


class AnnotationEvent(IntrospectionEventBase):
    """A member-authored annotation event."""

    event_name: Literal[IntrospectionEventName.ANNOTATION]
    payload: AnnotationPayload


class IssueActivityEvent(IntrospectionEventBase):
    """An issue change or comment (``event_name=introspection.issue``)."""

    event_name: Literal[IntrospectionEventName.ISSUE]
    payload: IssueActivityPayload


class JudgementEvent(IntrospectionEventBase):
    """A judge evaluation (``event_name=introspection.judgement``)."""

    event_name: Literal[IntrospectionEventName.JUDGEMENT]
    payload: JudgementPayload


class RoutineTriggeredEvent(IntrospectionEventBase):
    """A routine trigger that ran
    (``event_name=introspection.routines.triggered``)."""

    event_name: Literal[IntrospectionEventName.ROUTINE_TRIGGERED]
    payload: RoutineTriggeredPayload


class RoutineSkippedEvent(IntrospectionEventBase):
    """A scheduled routine trigger that ran nothing
    (``event_name=introspection.routines.skipped``)."""

    event_name: Literal[IntrospectionEventName.ROUTINE_SKIPPED]
    payload: RoutineSkippedPayload


class TrackEvent(IntrospectionEventBase):
    """An app event (``event_name=introspection.track``); the custom name
    is ``payload.name``."""

    event_name: Literal[IntrospectionEventName.TRACK]
    payload: TrackPayload


#: The discriminated union of the typed event families. Pydantic
#: selects the member from the top-level ``event_name`` tag; the member
#: fixes the ``payload`` type.
Event = Annotated[
    ObservationEvent
    | PatternEvent
    | PatternAssignmentEvent
    | ClusteringRunEvent
    | FeedbackEvent
    | AnnotationEvent
    | IssueActivityEvent
    | JudgementEvent
    | RoutineTriggeredEvent
    | RoutineSkippedEvent
    | TrackEvent,
    Field(discriminator="event_name"),
]


class UnknownEvent(IntrospectionEventBase):
    """Forward-compatible fallback for a family this SDK version predates.

    The closed :data:`Event` union exists so the payload type is fixed by
    the ``event_name`` tag. A family added server-side has no
    member to select, so it surfaces here with the envelope validated and
    ``payload`` left untyped, rather than raising. Paginated reads skip
    such rows (the caller named a family, so an off-family row is noise);
    :meth:`~introspection_sdk.runner_resources.events.Events.get` cannot,
    because the caller named an id and an error would make a new server
    family look like a missing event.
    """

    payload: Any = None
