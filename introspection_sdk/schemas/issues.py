"""Pydantic mirrors of DP ``/v1/issues`` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK. The status
and priority enums are open on read: a value this SDK does not know
decodes as a plain ``str`` instead of failing.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from introspection_sdk.schemas.tasks import TaskStatus

IssueMetadataValue = str | int | float | bool | None


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class IssueStatus(StrEnum):
    OPEN = "open"
    WAITING = "waiting"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class IssuePriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class IssueOwner(StrEnum):
    """``GET /v1/issues?owner=``: project-owned issues, or the caller's own
    private ones."""

    PROJECT = "project"
    ME = "me"


OpenIssueStatus = Annotated[
    IssueStatus | str, Field(union_mode="left_to_right")
]
OpenIssuePriority = Annotated[
    IssuePriority | str, Field(union_mode="left_to_right")
]
OpenTaskStatus = Annotated[TaskStatus | str, Field(union_mode="left_to_right")]


class IssueFile(_ApiModel):
    file_id: UUID
    name: str | None = None
    checksum: str | None = None
    source_event_ids: list[UUID] = Field(default_factory=list)


class IssueEventReference(_ApiModel):
    event_id: UUID


class IssueSpanReference(_ApiModel):
    trace_id: str
    span_id: str


class IssueLink(_ApiModel):
    url: str
    title: str | None = None


class IssueOpenRequest(_ApiModel):
    """One open human request on an issue."""

    id: UUID
    question: str
    assignee_id: UUID
    created_at: datetime


class Issue(_ApiModel):
    """A project pursuit: a living brief worked by a fixed worker task."""

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    title: str
    description: str
    priority: OpenIssuePriority = IssuePriority.MEDIUM
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, IssueMetadataValue] = Field(default_factory=dict)
    files: list[IssueFile] = Field(default_factory=list)
    links: list[IssueLink] = Field(default_factory=list)
    events: list[IssueEventReference] = Field(default_factory=list)
    spans: list[IssueSpanReference] = Field(default_factory=list)

    display_index: int | None = None
    status: OpenIssueStatus = IssueStatus.OPEN
    revision: int = 1
    task_id: UUID | None = None
    task_status: OpenTaskStatus | None = None
    member_id: UUID | None = None
    """Owning member of a private issue; ``None`` for a project-owned one."""
    closed_at: datetime | None = None
    open_requests: list[IssueOpenRequest] = Field(default_factory=list)

    @field_validator("open_requests", mode="before")
    @classmethod
    def _unprojected_requests(cls, value: object) -> object:
        return [] if value is None else value


class IssueCreateRequest(_ApiModel):
    """Body for ``POST /v1/issues``."""

    title: str
    description: str
    task_id: UUID
    priority: IssuePriority | str | None = None
    tags: list[str] | None = None
    metadata: dict[str, IssueMetadataValue] | None = None
    files: list[IssueFile] | None = None
    links: list[IssueLink] | None = None
    events: list[IssueEventReference] | None = None
    spans: list[IssueSpanReference] | None = None


class IssueUpdateRequest(_ApiModel):
    """Body for ``PATCH /v1/issues/{id}``: a brief edit at
    ``expected_revision``."""

    expected_revision: int
    title: str | None = None
    description: str | None = None
    priority: IssuePriority | str | None = None
    status: IssueStatus | str | None = None
    tags: list[str] | None = None
    metadata: dict[str, IssueMetadataValue] | None = None
    files: list[IssueFile] | None = None
    links: list[IssueLink] | None = None
    events: list[IssueEventReference] | None = None
    spans: list[IssueSpanReference] | None = None


__all__ = [
    "Issue",
    "IssueCreateRequest",
    "IssueEventReference",
    "IssueFile",
    "IssueLink",
    "IssueMetadataValue",
    "IssueOpenRequest",
    "IssueOwner",
    "IssuePriority",
    "IssueSpanReference",
    "IssueStatus",
    "IssueUpdateRequest",
    "OpenIssuePriority",
    "OpenIssueStatus",
]
