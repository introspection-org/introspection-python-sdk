"""Pydantic mirrors of DP `/v1/tasks` request/response models.

Mirrors `apps/dataplane-api/introspection_dataplane/models/task.py`.
Extra fields are tolerated so DP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from introspection_sdk.schemas.agui import ResumeEntry


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class TaskMode(StrEnum):
    AGENT = "agent"
    INTROSPECT = "introspect"
    SYSTEM_REVIEW = "system_review"
    SYSTEM_INSTRUMENTATION = "system_instrumentation"
    OBSERVATION_REVIEW = "observation_review"
    SECURITY_REVIEW = "security_review"
    REPO_INDEX = "repo_index"
    SYSTEM_DISCOVERY = "system_discovery"
    ONBOARDING = "onboarding"
    HEARTBEAT = "heartbeat"


class TaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    AWAITING_USER = "awaiting_user"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class AgentInfo(_ApiModel):
    sandbox_status: str | None = None
    session_id: str | None = None


class Task(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    display_index: int | None = None
    mode: TaskMode = TaskMode.AGENT
    status: TaskStatus = TaskStatus.PENDING
    member_id: UUID | None = None
    automation_id: UUID | None = None
    runtime_id: UUID | None = None
    is_archived: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_user_message_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    agent: AgentInfo | None = None
    identity_key: str | None = None


class TaskCreateRequest(_ApiModel):
    title: str | None = None
    prompt: str | None = None
    mode: TaskMode = TaskMode.AGENT
    system_id: str | None = None
    repository_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    idle_timeout_seconds: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Override the interactive idle window (seconds) before the "
            "sandbox is torn down. 0 tears down as soon as it's provisioned; "
            "omit to use the deployment default. Clamped to the task timeout."
        ),
    )
    fork_share_id: str | None = Field(
        default=None,
        description=(
            "Fork from a shared conversation: the /v1/shares grant id for the "
            "source conversation. Its presence makes this create a fork — the "
            "server seeds the new task with that conversation's history, read via "
            "the share (the permissions boundary)."
        ),
    )


class TaskUpdateRequest(_ApiModel):
    title: str | None = None
    is_archived: bool | None = None
    metadata: dict[str, Any] | None = None


class TaskPrompt(_ApiModel):
    text: str = Field(min_length=1)
    images: list[str] | None = None


class TaskRunKind(StrEnum):
    PROMPT = "prompt"
    STEER = "steer"


class TaskRunCreateRequest(_ApiModel):
    prompt: TaskPrompt | None = None
    message: str | None = None
    kind: TaskRunKind | None = None
    metadata: dict[str, Any] | None = None


class TaskRunResumeRequest(_ApiModel):
    resume: list[ResumeEntry]


class TaskRun(_ApiModel):
    id: str
    task_id: UUID
    status: TaskStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskCreateResponse(_ApiModel):
    task: Task
    run: TaskRun


class TaskRunResponse(_ApiModel):
    run: TaskRun


class TaskCancelResponse(_ApiModel):
    id: str


class TaskCancelMode(StrEnum):
    ABORT = "abort"
    DRAIN = "drain"


class TaskCancelRequest(_ApiModel):
    mode: TaskCancelMode = TaskCancelMode.ABORT
    drain_within_seconds: int | None = Field(default=None, ge=0)
