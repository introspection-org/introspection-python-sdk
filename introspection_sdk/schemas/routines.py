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
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from introspection_sdk.schemas.tasks import TaskRepoRequest


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RoutineTriggerType(StrEnum):
    """How a routine is triggered."""

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


class RoutineTriggerSource(StrEnum):
    """What an event trigger listens to."""

    INTEGRATION = "integration"
    """An org integration bound to the project (Slack, GitHub)."""
    CONNECTOR = "connector"
    """A project connector, named by ``connector_slug`` (a ``webhook``
    connector)."""


class RoutineTriggerProvider(StrEnum):
    """The provider whose events a trigger matches."""

    SLACK = "slack"
    LINEAR = "linear"
    GITHUB = "github"
    WEBHOOK = "webhook"


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
OpenTriggerSource = Annotated[
    RoutineTriggerSource | str, Field(union_mode="left_to_right")
]
OpenTriggerProvider = Annotated[
    RoutineTriggerProvider | str, Field(union_mode="left_to_right")
]

MAX_TRIGGER_PARAMETERS_BYTES = 16 * 1024
"""A manual trigger's ``parameters`` serialize to at most this many bytes
of JSON; the server answers 422 past it."""
MAX_TRIGGER_PARAMETERS_DEPTH = 8
"""Objects and arrays in a manual trigger's ``parameters`` nest at most
this deep; the server answers 422 past it."""


class RoutineCondition(_ApiModel):
    """One condition stored in a routine's metadata."""

    type: OpenConditionType
    runtime_group_id: UUID | None = None


class RoutineMetadata(_ApiModel):
    """The typed shape of a routine's ``metadata`` object.

    The runtime group is the routine's top-level ``runtime_group_id``;
    the server rejects one inside metadata. Unset fields are left out of
    the request, which matters for a member's own routine: the server
    accepts only ``cron_schedules`` and ``timezone`` from a non-admin.
    """

    cron_schedules: list[str] | None = None
    """Several cron expressions; ``cron_schedule`` on the routine is the
    single-schedule form."""
    timezone: str | None = None
    """IANA time zone the cron schedules are evaluated in."""
    repositories: list[TaskRepoRequest] | None = None
    """Repositories a task-backed routine clones."""
    conditions: list[RoutineCondition] | None = None
    operator_default: str | None = None
    """Set by the platform on a project's default routine
    (``project_check_in``)."""


class RoutineTriggerFilter(_ApiModel):
    """An event trigger's filter: every key set must contain the event's
    value for it. Which keys a provider takes is the server's catalogue:
    Slack ``channel_ids`` / ``emoji`` (``slack.message.posted`` requires
    ``channel_ids``), GitHub ``repository_ids`` / ``branches``, Linear
    ``team_ids`` / ``to_states``, and a webhook ``payload_fields``."""

    channel_ids: list[str] | None = None
    emoji: list[str] | None = None
    team_ids: list[str] | None = None
    to_states: list[str] | None = None
    repository_ids: list[str] | None = None
    branches: list[str] | None = None
    payload_fields: dict[str, list[str]] | None = None
    """A webhook body's top-level scalars, by key: a string matches as
    given, a number, boolean or ``null`` as its JSON text."""


class RoutineTriggerSpec(_ApiModel):
    """One entry of ``triggers`` on a routine create or update.

    With ``id`` it keeps that existing trigger, applying the fields given;
    without one it is a new trigger. ``parameters`` names values read from
    the event's JSON body by RFC 6901 pointer (``{"order_id":
    "/data/order/id"}``), which the prompt references as
    ``@parameters.<name>`` and the run receives as ``parameters.json``.
    """

    provider: OpenTriggerProvider
    event_types: list[str]
    """``{provider}.{object}.{action}`` names (``github.push``); a webhook
    connector takes the sender's own type names, or ``*`` alone for
    every one (a body with no string ``type`` arrives as
    ``webhook.received``)."""
    id: UUID | None = None
    source: OpenTriggerSource | None = None
    """``integration`` when omitted."""
    connector_slug: str | None = None
    """The project connector, set for a ``connector`` source only."""
    filter: RoutineTriggerFilter | None = None
    parameters: dict[str, str] | None = None
    enabled: bool | None = None


class RoutineTrigger(_ApiModel):
    """A stored event trigger on a routine."""

    id: UUID
    routine_id: UUID
    source: OpenTriggerSource
    provider: OpenTriggerProvider
    event_types: list[str]
    connector_slug: str | None = None
    filter: RoutineTriggerFilter = Field(default_factory=RoutineTriggerFilter)
    parameters: dict[str, str] = Field(default_factory=dict)
    """``{name: JSON pointer}`` into the event's body."""
    enabled: bool = True
    org_id: UUID | None = None
    project_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


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
    trigger_type: OpenTriggerType
    org_id: UUID | None = None
    project_id: UUID | None = None
    description: str | None = None
    enabled: bool = True
    cron_schedule: str | None = None
    kind: OpenKind | None = None
    """``None`` for a routine a person created."""
    prompt: str | None = None
    metadata: dict[str, Any] | None = None
    """Open-ended; read the known fields with :attr:`typed_metadata`."""
    tags: list[str] = []
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    """The next slot: derived from the schedule for ``cron``, client-set for
    a one-off ``manual`` routine and cleared once that slot fires."""
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
    triggers: list[RoutineTrigger] = []
    """Events that start a run, beside the schedule and a manual trigger."""

    @property
    def typed_metadata(self) -> RoutineMetadata | None:
        """``metadata`` parsed into :class:`RoutineMetadata`, or ``None``
        when it is absent or does not fit."""
        if self.metadata is None:
            return None
        try:
            return RoutineMetadata.model_validate(self.metadata)
        except ValidationError:
            return None


class RoutineCreateRequest(_ApiModel):
    """Body of ``POST /v1/routines``.

    A one-off reminder is a ``manual`` routine with a future
    ``next_trigger_at``; a ``cron`` routine derives its own slots and
    must not send one.
    """

    name: str
    trigger_type: OpenTriggerType
    description: str | None = None
    cron_schedule: str | None = None
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
    """A one-off slot for a ``manual`` routine; must be in the future
    and timezone-aware."""
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None
    triggers: list[RoutineTriggerSpec] | None = None
    """Event triggers (at most 20), for a prompt routine that starts a
    task per run; a new routine's triggers carry no ``id``."""


class RoutineUpdateRequest(_ApiModel):
    """Body of ``PATCH /v1/routines/{id}``.

    Only set fields are sent: ``None`` leaves a field as it is, so nothing
    can be cleared. ``kind`` and ``trigger_type`` are immutable;
    ``metadata`` replaces wholesale.
    """

    name: str | None = None
    description: str | None = None
    cron_schedule: str | None = None
    prompt: str | None = None
    runtime_group_id: UUID | None = None
    """Moves a prompt routine to another runtime group."""
    task_id: UUID | None = None
    next_trigger_at: AwareDatetime | None = None
    """Schedules, moves or re-arms a ``manual`` routine's one-off slot;
    must be in the future and timezone-aware."""
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None
    """``False`` pauses and keeps the slot."""
    triggers: list[RoutineTriggerSpec] | None = None
    """Replaces the routine's triggers: an entry with an ``id`` keeps that
    trigger, the rest are removed; ``[]`` removes them all."""


class RoutineTriggerRequest(_ApiModel):
    """Body of ``POST /v1/routines/{id}/trigger``.

    ``parameters`` is one JSON object, at most
    :data:`MAX_TRIGGER_PARAMETERS_BYTES` serialized and
    :data:`MAX_TRIGGER_PARAMETERS_DEPTH` levels deep. A prompt routine's
    run receives it as ``parameters.json`` and ``@parameters.<name>`` in
    its prompt; a platform routine reads the keys its kind defines
    (``observation_synthesis``: ``conversation_ids``, 1-100).
    """

    parameters: dict[str, Any] | None = None


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
    "Routine",
    "RoutineCondition",
    "RoutineConditionType",
    "RoutineCreateRequest",
    "RoutineExecutionStatus",
    "RoutineKind",
    "RoutineMetadata",
    "RoutineSkipReason",
    "RoutineRunSource",
    "RoutineTrigger",
    "RoutineTriggerEventRef",
    "RoutineTriggerFilter",
    "RoutineTriggerProvider",
    "RoutineTriggerRequest",
    "RoutineTriggerResponse",
    "RoutineTriggerSource",
    "RoutineTriggerSpec",
    "RoutineTriggerType",
    "RoutineUpdateRequest",
    "EnqueuedConversation",
    "MAX_TRIGGER_PARAMETERS_BYTES",
    "MAX_TRIGGER_PARAMETERS_DEPTH",
    "OpenConditionType",
    "OpenExecutionStatus",
    "OpenKind",
    "OpenSkipReason",
    "OpenTriggerProvider",
    "OpenTriggerSource",
    "OpenTriggerType",
]
