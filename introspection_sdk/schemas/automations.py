"""Pydantic mirrors of DP ``/v1/automations`` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.

The string enums here are **open**: each lists the values this SDK
knows, but a field typed with one also accepts any other string, which
decodes as a plain ``str`` instead of failing. A server that adds a new
automation kind, skip reason or condition therefore never breaks an
older client. Known values still decode as the enum member, and every
member compares equal to its wire string.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from introspection_sdk.schemas.tasks import TaskRepoRequest


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class AutomationTriggerType(StrEnum):
    """How an automation is triggered."""

    CRON = "cron"
    MANUAL = "manual"
    """Runs by hand, or once at a client-set ``next_trigger_at`` (a one-off
    reminder)."""


class AutomationKind(StrEnum):
    """A platform automation kind. An automation a person created has no
    kind (``None``)."""

    OBSERVATION_SYNTHESIS = "observation_synthesis"
    """Project-wide: takes no ``runtime_group_id``."""
    OBSERVATION_CLUSTERING = "observation_clustering"
    PROJECT_CHECK_IN = "project_check_in"
    """The project's default check-in. Runs as an agent task, so it carries
    a ``prompt``."""


class AutomationConditionType(StrEnum):
    """A built-in condition evaluated before an automation runs."""

    HAS_NEW_TASKS_SINCE_LAST_RUN = "has_new_tasks_since_last_run"
    LAST_RUN_ISSUES_RESOLVED = "last_run_issues_resolved"
    NO_LIVE_TASK_FOR_AUTOMATION = "no_live_task_for_automation"


class AutomationExecutionStatus(StrEnum):
    """Outcome of one automation execution attempt."""

    TRIGGERED = "triggered"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SKIPPED = "skipped"


class AutomationSkipReason(StrEnum):
    """Why a scheduled trigger ran nothing
    (``introspection.automation.skipped``)."""

    AUTOMATION_DELETED = "automation_deleted"
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


# Left-to-right tries the enum first and falls back to the raw string, so
# a known value is the member and an unknown one still decodes. Pydantic's
# default "smart" union would pick ``str`` for every input from a dict.
OpenTriggerType = Annotated[
    AutomationTriggerType | str, Field(union_mode="left_to_right")
]
OpenKind = Annotated[AutomationKind | str, Field(union_mode="left_to_right")]
OpenConditionType = Annotated[
    AutomationConditionType | str, Field(union_mode="left_to_right")
]
OpenExecutionStatus = Annotated[
    AutomationExecutionStatus | str, Field(union_mode="left_to_right")
]
OpenSkipReason = Annotated[
    AutomationSkipReason | str, Field(union_mode="left_to_right")
]


class AutomationCondition(_ApiModel):
    """One condition stored in an automation's metadata."""

    type: OpenConditionType
    runtime_group_id: UUID | None = None


class AutomationMetadata(_ApiModel):
    """The typed shape of an automation's ``metadata`` object.

    The runtime group is the automation's top-level ``runtime_group_id``;
    the server rejects one inside metadata. Unset fields are left out of
    the request, which matters for a member's own automation: the server
    accepts only ``cron_schedules`` and ``timezone`` from a non-admin.
    """

    cron_schedules: list[str] | None = None
    """Several cron expressions; ``cron_schedule`` on the automation is the
    single-schedule form."""
    timezone: str | None = None
    """IANA time zone the cron schedules are evaluated in."""
    repositories: list[TaskRepoRequest] | None = None
    """Repositories a task-backed automation clones."""
    conditions: list[AutomationCondition] | None = None


class Automation(_ApiModel):
    """A stored automation: scheduled agent work, or platform work when
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
    """``None`` for an automation a person created."""
    prompt: str | None = None
    metadata: dict[str, Any] | None = None
    """Open-ended; read the known fields with :attr:`typed_metadata`."""
    tags: list[str] = []
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    """The next slot: derived from the schedule for ``cron``, client-set for
    a one-off ``manual`` automation and cleared once that slot fires."""
    runtime_group_id: UUID | None = None
    """The runtime group it runs on (or clusters); ``None`` for
    ``observation_synthesis``."""
    task_id: UUID | None = None
    """The existing task each firing posts the prompt into; ``None`` creates
    a task per firing."""
    created_by_member_id: UUID | None = None
    execution_blocked_reason: str | None = None
    """Why the scheduler will not run this automation, when it will not."""
    can_manage: bool = False
    """Whether the caller may edit it."""
    owner_role: str | None = None
    """``operator`` for one that runs as a task (a prompt automation or
    ``project_check_in``), ``None`` otherwise."""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def typed_metadata(self) -> AutomationMetadata | None:
        """``metadata`` parsed into :class:`AutomationMetadata`, or ``None``
        when it is absent or does not fit."""
        if self.metadata is None:
            return None
        try:
            return AutomationMetadata.model_validate(self.metadata)
        except ValidationError:
            return None


class AutomationCreateRequest(_ApiModel):
    """Body of ``POST /v1/automations``.

    A one-off reminder is a ``manual`` automation with a future
    ``next_trigger_at``; a ``cron`` automation derives its own slots and
    must not send one.
    """

    name: str
    trigger_type: OpenTriggerType
    description: str | None = None
    cron_schedule: str | None = None
    kind: OpenKind | None = None
    """Omit for a prompt automation, which then needs ``prompt``."""
    prompt: str | None = None
    runtime_group_id: UUID | None = None
    """Required unless ``kind`` is ``observation_synthesis``, which must
    omit it."""
    task_id: UUID | None = None
    """An existing task each firing posts the prompt into (prompt
    automations only)."""
    next_trigger_at: datetime | None = None
    """A one-off slot for a ``manual`` automation; must be in the future
    and timezone-aware."""
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None


class AutomationUpdateRequest(_ApiModel):
    """Body of ``PATCH /v1/automations/{id}``.

    Only set fields are sent: ``None`` leaves a field as it is, so nothing
    can be cleared. ``kind`` and ``trigger_type`` are immutable;
    ``metadata`` replaces wholesale.
    """

    name: str | None = None
    description: str | None = None
    cron_schedule: str | None = None
    prompt: str | None = None
    runtime_group_id: UUID | None = None
    """Moves a prompt automation to another runtime group."""
    task_id: UUID | None = None
    next_trigger_at: datetime | None = None
    """Schedules, moves or re-arms a ``manual`` automation's one-off slot;
    must be in the future and timezone-aware."""
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None
    """``False`` pauses and keeps the slot."""


class AutomationTriggerResponse(_ApiModel):
    """Response of a hand trigger (``202``). A ``skipped`` status carries
    its ``reason`` and records no event."""

    status: OpenExecutionStatus
    automation_id: UUID | None = None
    task_id: UUID | None = None
    """The task created, or posted into."""
    reason: str | None = None


__all__ = [
    "Automation",
    "AutomationCondition",
    "AutomationConditionType",
    "AutomationCreateRequest",
    "AutomationExecutionStatus",
    "AutomationKind",
    "AutomationMetadata",
    "AutomationSkipReason",
    "AutomationTriggerResponse",
    "AutomationTriggerType",
    "AutomationUpdateRequest",
    "OpenConditionType",
    "OpenExecutionStatus",
    "OpenKind",
    "OpenSkipReason",
    "OpenTriggerType",
]
