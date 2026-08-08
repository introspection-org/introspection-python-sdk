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


class TaskKind(StrEnum):
    """The execution shape of a task.

    ``AGENT`` boots the runtime-agent image and runs an interactive LLM agent;
    ``PROCESS`` runs a one-shot baked script and reports through the same
    completion path. This replaced the retired ``TaskMode``: there are no task
    modes any more — every agent task is a conversation, and the recipe agent
    is selected by ``agent_name``.
    """

    AGENT = "agent"
    PROCESS = "process"


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
    kind: TaskKind = TaskKind.AGENT
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


class TaskFileRef(_ApiModel):
    """A reference to an already-uploaded file, attached to a task.

    Bytes go through ``POST /v1/files`` first (``runner.files.upload`` /
    ``create_text``); a task only ever carries the reference.

    ``name`` is optional — omit it and the file is mounted under its own name.
    Supply it only to override: rename, or nest it in a subdirectory
    (``"specs/senior-jd.pdf"``). When supplied it must be relative and must not
    traverse outside the task's files directory.
    """

    id: str
    name: str | None = None
    size_bytes: int | None = None


class TaskRepoRequest(_ApiModel):
    """One ``repositories[]`` entry: a repository plus the state to clone it at.

    The recipe's ``runtime.github.repositories`` grant decides what a runtime
    MAY clone; this decides what a task DOES clone, and at what ref. An entry
    outside the grant is dropped by the server, never a launch failure.
    """

    repo: str = Field(description='Registered repository slug, "owner/name".')
    ref: str | None = Field(
        default=None,
        description=(
            "Branch, tag, or commit to check out. Omitted uses the "
            "repository's registered default branch."
        ),
    )
    depth: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Shallow-clone depth; 0 clones full history. Omitted uses the "
            "platform default."
        ),
    )


class TaskCreateRequest(_ApiModel):
    # Task creation through a Runner gets its Runtime authority from the
    # Runner credential. Keep response models forward-compatible, but do not
    # forward undeclared create fields such as the browser-only `runtime_id`.
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    prompt: str | None = None
    agent_name: str | None = Field(
        default=None,
        description=(
            "Recipe agent to run; omit for the recipe default "
            "(agents/agent.yaml)."
        ),
    )
    repositories: list[TaskRepoRequest] | None = Field(
        default=None,
        max_length=10,
        description=(
            "Workspace repositories to clone into the sandbox's "
            "workspace/repos/ before the first turn, at most 10."
        ),
    )
    metadata: dict[str, Any] | None = None
    files: list[TaskFileRef] | None = Field(
        default=None,
        description=(
            "Files to attach to this task. Materialized into the agent's "
            "workspace and announced to it before the first turn runs. "
            "Equivalent to setting metadata.conversation_files.uploads, which "
            "stays supported; prefer this field."
        ),
    )
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
    kind: TaskRunKind | None = None
    metadata: dict[str, Any] | None = None
    files: list[TaskFileRef] | None = Field(
        default=None,
        description=(
            "Files to attach to this turn — the way to add a file "
            "mid-conversation. The agent's workspace is built once when its "
            "sandbox starts, so a file attached on a later turn is "
            "materialized into the running sandbox before that turn executes, "
            "and joins the task's set so a restart replays it. Re-sending a "
            "file the task already carries is a no-op. Not accepted alongside "
            "resume."
        ),
    )


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
