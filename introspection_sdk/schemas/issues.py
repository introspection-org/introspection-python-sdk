"""Pydantic mirrors of DP ``/v1/issues`` request/response models.

An issue is a brief (title, description, priority, status) with the
evidence it cites (files, links, events, spans), the human requests still
open on it, and a fixed worker Task that carries its chat.

Response models tolerate unknown fields (``extra="allow"``) so a DP
addition never breaks the SDK; request bodies forbid them, as the server
does. The status and priority enums are **open** on a response: a value
this SDK does not know yet decodes as a plain ``str``.

:class:`IssueUpdate` is dumped with ``exclude_unset=True``: a field left
unset is omitted and left as it is, while an explicit ``[]`` (or ``{}``
for ``metadata``) is sent and clears it, since each list replaces its list
wholesale.

:attr:`Issue.etag` is the issue's version for ``If-Match`` on an update or
delete, so a write made against a stale read is refused with 412.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from introspection_sdk._uuid import _uuid7
from introspection_sdk.schemas.tasks import TaskStatus

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IssueStatus(StrEnum):
    """Issue status."""

    OPEN = "open"
    WAITING = "waiting"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class IssuePriority(StrEnum):
    """Issue priority."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class IssueOwner(StrEnum):
    """``GET /v1/issues?owner=``: project-owned issues, or the caller's own
    private ones."""

    PROJECT = "project"
    """Project-owned (Operator) issues."""
    ME = "me"
    """The caller's own private issues."""


class IssueRequestStatus(StrEnum):
    """Status of one human request on an issue."""

    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


OpenIssueStatus = Annotated[
    IssueStatus | str, Field(union_mode="left_to_right")
]
OpenIssuePriority = Annotated[
    IssuePriority | str, Field(union_mode="left_to_right")
]
OpenTaskStatus = Annotated[TaskStatus | str, Field(union_mode="left_to_right")]

IssueMetadataValue = str | int | float | bool | None
"""One value of an issue's ``metadata`` document."""


class IssueFile(ApiModel):
    """A Data Plane file cited as evidence."""

    file_id: UUID
    name: str | None = None
    checksum: str | None = None
    source_event_ids: list[UUID] = Field(default_factory=list, max_length=100)


class IssueLink(ApiModel):
    """An HTTP or HTTPS link cited as evidence, such as a pull request."""

    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=500)


class IssueEventReference(ApiModel):
    """A recorded event cited as evidence; the caller must be able to read
    it."""

    event_id: UUID


class IssueSpanReference(ApiModel):
    """A conversation span cited as evidence; the caller must be able to
    read the exact pair."""

    trace_id: str = Field(pattern=r"^[0-9a-fA-F]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-fA-F]{16}$")


class IssueOpenRequest(ApiModel):
    """One open human request, projected onto its issue."""

    id: UUID
    question: str
    assignee_id: UUID
    created_at: datetime


class Issue(ApiModel):
    """A stored issue: the brief, its evidence and its open requests."""

    id: UUID
    org_id: UUID
    project_id: UUID
    title: str
    description: str
    priority: OpenIssuePriority = IssuePriority.MEDIUM
    status: OpenIssueStatus = IssueStatus.OPEN
    revision: int = 1
    files: list[IssueFile] = Field(default_factory=list)
    links: list[IssueLink] = Field(default_factory=list)
    events: list[IssueEventReference] = Field(default_factory=list)
    spans: list[IssueSpanReference] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    """Free-form tags, conventionally ``key:value``."""
    metadata: dict[str, IssueMetadataValue] = Field(default_factory=dict)
    display_index: int | None = None
    """Project-scoped display ID."""
    task_id: UUID | None = None
    """The fixed worker Task that carries the issue's chat."""
    task_status: OpenTaskStatus | None = None
    """Current status of the worker Task."""
    member_id: UUID | None = None
    """Owning member of a private issue; ``None`` for a project-owned
    (Operator) issue."""
    closed_at: datetime | None = None
    """When the issue last entered ``closed`` or ``cancelled``."""
    open_requests: list[IssueOpenRequest] = Field(default_factory=list)
    """Open human requests, oldest first."""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def etag(self) -> str:
        """The issue's version as the server's ``ETag``: ``updated_at`` in
        whole milliseconds since the Unix epoch, quoted. Pass it as
        ``if_match`` to refuse a write if the issue changed since this
        read."""
        if self.updated_at is None:
            raise ValueError("An issue without updated_at has no ETag")
        updated_at = self.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        millis = (updated_at - _EPOCH) // timedelta(milliseconds=1)
        return f'"{millis}"'


class IssueEvidence(RequestModel):
    """The evidence and labels an issue's create and update bodies share.

    On an update each one replaces its list wholesale: ``[]`` clears it,
    ``{}`` clears ``metadata``.
    """

    files: list[IssueFile] | None = Field(default=None, max_length=200)
    links: list[IssueLink] | None = Field(default=None, max_length=200)
    events: list[IssueEventReference] | None = Field(
        default=None, max_length=50
    )
    spans: list[IssueSpanReference] | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    metadata: dict[str, IssueMetadataValue] | None = None


class IssueCreate(IssueEvidence):
    """Body of ``POST /v1/issues``. The issue starts ``open``."""

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=50000)
    task_id: UUID
    """The fixed worker Task used by the issue chat and Slack replies."""
    priority: IssuePriority | None = None
    """The server defaults to ``medium``."""


class IssueUpdate(IssueEvidence):
    """Edit an issue's brief (``PATCH /v1/issues/{id}``).

    Only the fields you set are sent: each list replaces its list wholesale
    and ``[]`` clears it, ``{}`` clears ``metadata``. To refuse the edit if
    the issue changed since you read it, pass that read's
    :attr:`Issue.etag` as ``if_match``.
    """

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(
        default=None, min_length=1, max_length=50000
    )
    priority: IssuePriority | None = None
    status: IssueStatus | None = None


class IssueRequestMutation(RequestModel):
    """Create one human request on an issue, or change one.

    ``expected_revision=0`` creates the request and needs ``question`` and
    ``assignee_id``; ``id`` is minted (a UUIDv7) when left out. Otherwise
    ``id`` names the request and ``expected_revision`` is its current
    revision; a stale one answers 409. ``resolved`` and ``cancelled`` need a
    ``resolution``.
    """

    id: UUID = Field(default_factory=_uuid7)
    expected_revision: int = Field(ge=0)
    question: str | None = Field(default=None, min_length=1, max_length=10000)
    assignee_id: UUID | None = None
    """Set again to reassign."""
    status: IssueRequestStatus | None = None
    resolution: str | None = Field(
        default=None, min_length=1, max_length=10000
    )
    """The decision and its basis, when closing."""

    @model_validator(mode="after")
    def _create_names_question_and_assignee(self) -> Self:
        if self.expected_revision == 0 and (
            self.question is None or self.assignee_id is None
        ):
            raise ValueError(
                "Creating a request (expected_revision=0) needs a question "
                "and an assignee_id"
            )
        return self


class IssueMutation(RequestModel):
    """``PATCH /v1/issues/{id}`` with ``{"request": {...}}``: create or
    change one human request."""

    request: IssueRequestMutation


__all__ = [
    "Issue",
    "IssueCreate",
    "IssueEvidence",
    "IssueEventReference",
    "IssueFile",
    "IssueLink",
    "IssueMetadataValue",
    "IssueMutation",
    "IssueOpenRequest",
    "IssueOwner",
    "IssuePriority",
    "IssueRequestMutation",
    "IssueRequestStatus",
    "IssueSpanReference",
    "IssueStatus",
    "IssueUpdate",
    "OpenIssuePriority",
    "OpenIssueStatus",
    "OpenTaskStatus",
]
