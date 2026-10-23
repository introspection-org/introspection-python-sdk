"""Pydantic mirrors of DP ``/v1/tasks/{id}/commands`` models.

A command is ``exec``, ``upload`` or ``download`` against an eval task's live
sandbox: a row the task's workflow executes and stamps. The create returns it
``queued``; a read reports its outcome. ``service`` names a compose service;
``None`` (or ``main``) is the agent's own container.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class TaskCommandKind(StrEnum):
    EXEC = "exec"
    UPLOAD = "upload"
    DOWNLOAD = "download"


class TaskCommandStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Whether the command has finished, either way."""
        return self in (TaskCommandStatus.COMPLETED, TaskCommandStatus.FAILED)


class ExecCommand(BaseModel):
    """Run an argv (never a shell string) and record its exit and output."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["exec"] = "exec"
    command: list[str] = Field(min_length=1)
    cwd: str | None = None
    timeout_seconds: int | None = None
    """Defaults to 300 server-side."""
    service: str | None = None


class UploadCommand(BaseModel):
    """Copy a Files API object to an absolute ``path`` inside the sandbox."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["upload"] = "upload"
    file_id: UUID
    path: str


class DownloadCommand(BaseModel):
    """Copy the file at an absolute ``path`` out into a new Files API object,
    reported as :attr:`TaskCommand.output_file_id`."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["download"] = "download"
    path: str
    service: str | None = None


TaskCommandSpec = Annotated[
    ExecCommand | UploadCommand | DownloadCommand,
    Field(discriminator="kind"),
]
"""Body of ``POST /v1/tasks/{id}/commands``, tagged by ``kind``."""

TASK_COMMAND_SPEC_ADAPTER: TypeAdapter[TaskCommandSpec] = TypeAdapter(
    TaskCommandSpec
)


class TaskCommand(BaseModel):
    """A recorded command and, once terminal, its outcome."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    task_id: UUID
    kind: TaskCommandKind
    spec: dict[str, Any]
    """The spec as the API normalized it."""
    status: TaskCommandStatus
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    output_file_id: UUID | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


__all__ = [
    "TASK_COMMAND_SPEC_ADAPTER",
    "DownloadCommand",
    "ExecCommand",
    "TaskCommand",
    "TaskCommandKind",
    "TaskCommandSpec",
    "TaskCommandStatus",
    "UploadCommand",
]
