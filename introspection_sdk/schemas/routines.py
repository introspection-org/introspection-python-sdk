"""Pydantic mirrors of DP ``/v1/routines`` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.

The string enums here are **open**: each lists the values this SDK
knows, but a field typed with one also accepts any other string, which
decodes as a plain ``str`` instead of failing. A server that adds a new
routine kind, skip reason or condition therefore never breaks an
older client. Known values still decode as the enum member, and every
member compares equal to its wire string.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
)

from introspection_sdk.schemas.tasks import TaskFileRef, TaskRepoRequest


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RoutineTriggerType(StrEnum):
    """How a run was started, as ``trigger_type`` on the
    ``introspection.routines.triggered`` / ``.skipped`` payloads."""

    CRON = "cron"
    MANUAL = "manual"
    """Runs by hand, or once at a client-set ``next_trigger_at`` (a one-off
    reminder)."""


class RoutineKind(StrEnum):
    """A platform routine kind. A routine a person created has no
    kind (``None``)."""

    OBSERVATION_SYNTHESIS = "observation_synthesis"
    """Project-wide: takes no ``runtime_group_id``."""
    OBSERVATION_CLUSTERING = "observation_clustering"
    PROJECT_CHECK_IN = "project_check_in"
    """The project's default check-in. Runs as an agent task, so it carries
    a ``prompt``."""


class RoutineConditionType(StrEnum):
    """A built-in condition evaluated before a routine runs."""

    HAS_NEW_TASKS_SINCE_LAST_RUN = "has_new_tasks_since_last_run"
    LAST_RUN_ISSUES_RESOLVED = "last_run_issues_resolved"
    NO_LIVE_TASK_FOR_ROUTINE = "no_live_task_for_routine"


class RoutineExecutionStatus(StrEnum):
    """Outcome of one routine execution attempt."""

    TRIGGERED = "triggered"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SKIPPED = "skipped"


class RoutineSkipReason(StrEnum):
    """Why a scheduled trigger ran nothing
    (``introspection.routines.skipped``)."""

    ROUTINE_DELETED = "routine_deleted"
    EXECUTION_BLOCKED = "execution_blocked"
    CONDITIONS_NOT_MET = "conditions_not_met"
    NO_PRODUCTION_RUNTIME = "no_production_runtime"
    SLACK_NOT_CONFIGURED = "slack_not_configured"
    TARGET_TASK_DELETED = "target_task_deleted"
    TARGET_TASK_ARCHIVED = "target_task_archived"
    TARGET_TASK_UNAVAILABLE = "target_task_unavailable"
    TARGET_TASK_REFUSED = "target_task_refused"
    TARGET_BUSY = "target_busy"
    """The target task stayed mid-turn through every retry."""
    TRIGGER_BUSY = "trigger_busy"
    """An event arrived while the run its trigger last started was still in
    flight; the payload's ``event`` names the delivery."""


class RoutineRunSource(StrEnum):
    """What started a routine's run, stamped on its task's metadata as
    ``trigger_source``."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"
    TRIGGER = "trigger"
    """An event trigger; the task's metadata ``routine_trigger`` holds its
    :class:`RoutineTriggerEventRef`."""


# Left-to-right tries the enum first and falls back to the raw string, so
# a known value is the member and an unknown one still decodes. Pydantic's
# default "smart" union would pick ``str`` for every input from a dict.
OpenTriggerType = Annotated[
    RoutineTriggerType | str, Field(union_mode="left_to_right")
]
OpenKind = Annotated[RoutineKind | str, Field(union_mode="left_to_right")]
OpenConditionType = Annotated[
    RoutineConditionType | str, Field(union_mode="left_to_right")
]
OpenExecutionStatus = Annotated[
    RoutineExecutionStatus | str, Field(union_mode="left_to_right")
]
OpenSkipReason = Annotated[
    RoutineSkipReason | str, Field(union_mode="left_to_right")
]

MAX_TRIGGER_PARAMETERS_BYTES = 16 * 1024
"""A manual trigger's ``parameters`` serialize to at most this many bytes
of JSON; the server answers 422 past it."""
MAX_TRIGGER_PARAMETERS_DEPTH = 8
"""Objects and arrays in a manual trigger's ``parameters`` nest at most
this deep; the server answers 422 past it."""


class RoutineCondition(_ApiModel):
    """A built-in condition the routine checks before it runs."""

    type: OpenConditionType
    runtime_group_id: UUID | None = None


class RoutineSynthesis(_ApiModel):
    """How an ``observation_synthesis`` routine runs."""

    max_conversations: int | None = None


class ScheduleTriggerSpec(_ApiModel):
    """A cron schedule. ``timezone`` is IANA, UTC when unset."""

    type: Literal["schedule"] = "schedule"
    cron: str
    timezone: str | None = None
    id: UUID | None = None
    """Keeps that existing trigger; omit for a new one."""


class SlackTriggerSpec(_ApiModel):
    """Slack events; ``slack.message.posted`` requires ``channel_ids``."""

    type: Literal["slack"] = "slack"
    event_types: list[str]
    channel_ids: list[str] | None = None
    emoji: list[str] | None = None
    id: UUID | None = None


class GitHubTriggerSpec(_ApiModel):
    """GitHub events."""

    type: Literal["github"] = "github"
    event_types: list[str]
    repository_ids: list[str] | None = None
    branches: list[str] | None = None
    id: UUID | None = None


class LinearTriggerSpec(_ApiModel):
    """Linear events, from the teams bound to the project."""

    type: Literal["linear"] = "linear"
    event_types: list[str]
    to_states: list[str] | None = None
    id: UUID | None = None


class WebhookTriggerSpec(_ApiModel):
    """Events posted to a project's webhook connector. ``event_types`` are
    the sender's own names, or ``*`` alone for every one."""

    type: Literal["webhook"] = "webhook"
    connector_slug: str
    event_types: list[str]
    payload_fields: dict[str, list[str]] | None = None
    """A body's top-level scalars, by key: a string matches as given, a
    number, boolean or ``null`` as its JSON text."""
    id: UUID | None = None


class UnknownTriggerSpec(_ApiModel):
    """A trigger ``type`` this SDK does not model, sent as given."""

    open_schema: ClassVar[bool] = True

    type: str
    id: UUID | None = None


class ScheduleTrigger(ScheduleTriggerSpec):
    id: UUID


class SlackTrigger(SlackTriggerSpec):
    id: UUID


class GitHubTrigger(GitHubTriggerSpec):
    id: UUID


class LinearTrigger(LinearTriggerSpec):
    id: UUID


class WebhookTrigger(WebhookTriggerSpec):
    id: UUID


class UnknownTrigger(UnknownTriggerSpec):
    """A stored trigger whose ``type`` this SDK predates; its other fields
    are kept as extras."""

    id: UUID


TRIGGER_TYPES = frozenset({"schedule", "slack", "github", "linear", "webhook"})


def _trigger_tag(value: Any) -> str:
    kind = (
        value.get("type")
        if isinstance(value, dict)
        else getattr(value, "type", None)
    )
    return kind if kind in TRIGGER_TYPES else "unknown"


RoutineTrigger = Annotated[
    Annotated[ScheduleTrigger, Tag("schedule")]
    | Annotated[SlackTrigger, Tag("slack")]
    | Annotated[GitHubTrigger, Tag("github")]
    | Annotated[LinearTrigger, Tag("linear")]
    | Annotated[WebhookTrigger, Tag("webhook")]
    | Annotated[UnknownTrigger, Tag("unknown")],
    Discriminator(_trigger_tag),
]
"""A stored trigger, discriminated on ``type``."""

RoutineTriggerSpec = Annotated[
    Annotated[ScheduleTriggerSpec, Tag("schedule")]
    | Annotated[SlackTriggerSpec, Tag("slack")]
    | Annotated[GitHubTriggerSpec, Tag("github")]
    | Annotated[LinearTriggerSpec, Tag("linear")]
    | Annotated[WebhookTriggerSpec, Tag("webhook")]
    | Annotated[UnknownTriggerSpec, Tag("unknown")],
    Discriminator(_trigger_tag),
]
"""One entry of ``triggers`` on a create or update, discriminated on
``type``. A stored :data:`RoutineTrigger` is one too, keeping its ``id``.

An event-started run receives the event's body as ``parameters.json``, and
``@parameters.<key>`` reads its top-level keys, as a manual run's
``parameters`` do."""


class RoutineTriggerEventRef(_ApiModel):
    """The event trigger a run or skip answered. Carried as ``event`` on
    ``introspection.routines.triggered`` / ``.skipped`` payloads and as
    ``routine_trigger`` in a trigger-started task's metadata."""

    trigger_id: UUID
    event_type: str
    delivery_id: str
    """The provider event's identity within its source; a redelivery
    repeats it."""


class Routine(_ApiModel):
    """A stored routine: scheduled agent work, or platform work when
    ``kind`` is set."""

    id: UUID
    name: str
    org_id: UUID | None = None
    project_id: UUID | None = None
    description: str | None = None
    enabled: bool = True
    kind: OpenKind | None = None
    """``None`` for a routine a person created."""
    prompt: str | None = None
    tags: list[str] = []
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    """The next slot: the earliest across its ``schedule`` triggers, or,
    with none, a client-set one-off cleared once it fires."""
    runtime_group_id: UUID | None = None
    """The runtime group it runs on (or clusters); ``None`` for
    ``observation_synthesis``."""
    task_id: UUID | None = None
    """The existing task each firing posts the prompt into; ``None`` creates
    a task per firing."""
    agent_member_id: UUID | None = None
    created_by_member_id: UUID | None = None
    execution_blocked_reason: str | None = None
    """Why the scheduler will not run this routine, when it will not."""
    can_manage: bool = False
    """Whether the caller may edit it."""
    owner_role: str | None = None
    """``operator`` for one that runs as a task (a prompt routine or
    ``project_check_in``), ``None`` otherwise."""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    """Set on a soft-deleted routine, which ``get`` still returns."""
    repositories: list[TaskRepoRequest] = []
    """Repositories a task-backed routine clones."""
    conditions: list[RoutineCondition] = []
    synthesis: RoutineSynthesis | None = None
    """Set on an ``observation_synthesis`` routine only."""
    triggers: list[RoutineTrigger] = []
    """What starts it besides a manual trigger: schedules and events."""


class RoutineCreateRequest(_ApiModel):
    """Body of ``POST /v1/routines``.

    A one-off reminder is a routine with no ``schedule`` trigger and a
    future ``next_trigger_at``.
    """

    name: str
    description: str | None = None
    kind: OpenKind | None = None
    """Omit for a prompt routine, which then needs ``prompt``."""
    prompt: str | None = None
    runtime_group_id: UUID | None = None
    """Required unless ``kind`` is ``observation_synthesis``, which must
    omit it."""
    task_id: UUID | None = None
    """An existing task each firing posts the prompt into (prompt
    routines only)."""
    next_trigger_at: AwareDatetime | None = None
    """A one-off slot, only without a ``schedule`` trigger; must be in
    the future and timezone-aware."""
    enabled: bool | None = None
    repositories: list[TaskRepoRequest] | None = None
    conditions: list[RoutineCondition] | None = None
    synthesis: RoutineSynthesis | None = None
    triggers: list[RoutineTriggerSpec] | None = None
    """At most 20. Event triggers are an administrator's, on a prompt
    routine that starts a task per run; a platform routine takes only
    ``schedule`` triggers."""


class RoutineUpdateRequest(_ApiModel):
    """Body of ``PATCH /v1/routines/{id}``.

    Only set fields are sent: ``None`` leaves a field as it is, so nothing
    can be cleared. ``kind`` is immutable.
    """

    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    runtime_group_id: UUID | None = None
    """Moves a prompt routine to another runtime group."""
    task_id: UUID | None = None
    next_trigger_at: AwareDatetime | None = None
    """Schedules, moves or re-arms a one-off slot on a routine with no
    ``schedule`` trigger; must be in the future and timezone-aware."""
    enabled: bool | None = None
    """``False`` pauses and keeps the slot."""
    repositories: list[TaskRepoRequest] | None = None
    conditions: list[RoutineCondition] | None = None
    synthesis: RoutineSynthesis | None = None
    triggers: list[RoutineTriggerSpec] | None = None
    """Replaces the routine's triggers: an entry with an ``id`` keeps that
    trigger, one without adds one, the rest are removed; ``[]`` removes
    them all."""


class RoutineTriggerRequest(_ApiModel):
    """Body of ``POST /v1/routines/{id}/trigger``.

    ``parameters`` is one JSON object, at most
    :data:`MAX_TRIGGER_PARAMETERS_BYTES` serialized and
    :data:`MAX_TRIGGER_PARAMETERS_DEPTH` levels deep. A prompt routine's
    run receives it as ``parameters.json`` and ``@parameters.<name>`` in
    its prompt; a platform routine reads the keys its kind defines
    (``observation_synthesis``: ``conversation_ids``, 1-100).

    ``files`` (at most 100) are attached to the run's new task, as on
    ``POST /v1/tasks``; only a prompt routine that starts a task per run
    takes them. One named ``parameters.json`` is the run's parameters
    file: with no inline ``parameters`` the server reads it (a JSON object,
    at most 256 KiB) as the parameters. Inline ``parameters`` win.
    """

    parameters: dict[str, Any] | None = None
    files: list[TaskFileRef] | None = None


class EnqueuedConversation(_ApiModel):
    """One entry of an ``observation_synthesis`` trigger's
    ``result["conversations"]``: a conversation it queued, and the end it
    queued it at."""

    conversation_id: str
    completed_at: AwareDatetime
    """Its ``introspection.observation_synthesis.completed`` event answers
    this trigger once that event's ``conversation_completed_at`` is at or
    after this."""


class RoutineTriggerResponse(_ApiModel):
    """Response of a manual trigger (``202``). A ``skipped`` status carries
    its ``reason`` and records no event."""

    status: OpenExecutionStatus
    routine_id: UUID | None = None
    task_id: UUID | None = None
    """The task created, or posted into."""
    run_id: UUID | None = None
    """The run this trigger started, when it has one, such as the run an
    ``observation_clustering`` routine's
    ``introspection.observation_clustering.run`` events carry."""
    reason: str | None = None
    result: dict[str, Any] | None = None
    """What the run reports, by kind. ``observation_synthesis``:
    ``enqueued``, the number of conversations sent to the synthesis
    queue, and, for named ``conversation_ids``, ``conversations``: a list
    shaped as :class:`EnqueuedConversation`."""


__all__ = [
    "GitHubTrigger",
    "GitHubTriggerSpec",
    "LinearTrigger",
    "LinearTriggerSpec",
    "Routine",
    "RoutineCondition",
    "RoutineConditionType",
    "RoutineCreateRequest",
    "RoutineExecutionStatus",
    "RoutineKind",
    "RoutineSkipReason",
    "RoutineSynthesis",
    "RoutineRunSource",
    "RoutineTrigger",
    "RoutineTriggerEventRef",
    "RoutineTriggerRequest",
    "RoutineTriggerResponse",
    "RoutineTriggerSpec",
    "RoutineTriggerType",
    "RoutineUpdateRequest",
    "ScheduleTrigger",
    "ScheduleTriggerSpec",
    "SlackTrigger",
    "SlackTriggerSpec",
    "TRIGGER_TYPES",
    "UnknownTrigger",
    "UnknownTriggerSpec",
    "WebhookTrigger",
    "WebhookTriggerSpec",
    "EnqueuedConversation",
    "MAX_TRIGGER_PARAMETERS_BYTES",
    "MAX_TRIGGER_PARAMETERS_DEPTH",
    "OpenConditionType",
    "OpenExecutionStatus",
    "OpenKind",
    "OpenSkipReason",
    "OpenTriggerType",
]
