"""Pydantic mirrors of DP ``/v1/issues`` request/response models.

An issue is a brief (title, description, priority, status) on a fixed
worker Task that carries its chat, the people on it (creator, assignee,
reviewer, followers), the evidence it cites (its attachments: links,
files, events and spans) and its comments. The related lists are read
with ``include`` and are ``None`` when not asked for.

Response models tolerate unknown fields (``extra="allow"``) so a DP
addition never breaks the SDK; request bodies forbid them, as the server
does. The status and priority enums are **open** on a response: a value
this SDK does not know yet decodes as a plain ``str``.

:class:`IssueUpdate` is dumped with ``exclude_unset=True``: a field left
unset is omitted and left as it is, while an explicit ``[]`` (or ``{}``
for ``metadata``) is sent and clears it, since each list replaces its list
wholesale, and an explicit ``None`` for ``assignee_member_id`` or
``reviewer_member_id`` is sent and clears that person. Attachments change
by ``add_attachments`` and ``remove_attachments`` instead, which need no
``If-Match``.

The ``links``, ``files``, ``events`` and ``spans`` lists are deprecated in
favour of ``attachments``; the server keeps them for one release cycle.

:attr:`Issue.etag` is the issue's version for ``If-Match`` on an update or
delete, so a write made against a stale read is refused with 412.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
)

from introspection_sdk.schemas.events import tag_or_unknown
from introspection_sdk.schemas.tasks import TaskStatus


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


class IssueMemberRelation(StrEnum):
    """How a member stands to an issue."""

    CREATOR = "creator"
    ASSIGNEE = "assignee"
    REVIEWER = "reviewer"
    FOLLOWER = "follower"


IssueInclude = Literal["members", "attachments", "comments"]
"""The related lists a single-issue read returns with the brief, passed as
a repeated ``include`` query param."""

IssueStoredInclude = Literal["members", "attachments"]
"""The related lists a list read or a write may return. ``comments`` is on
the single-issue read only."""

OpenIssueStatus = Annotated[
    IssueStatus | str, Field(union_mode="left_to_right")
]
OpenIssuePriority = Annotated[
    IssuePriority | str, Field(union_mode="left_to_right")
]
OpenIssueMemberRelation = Annotated[
    IssueMemberRelation | str, Field(union_mode="left_to_right")
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


ATTACHMENT_KINDS = frozenset({"link", "file", "event", "span"})
"""The attachment kinds this SDK models."""

DEPRECATED_READ = "read `attachments`"
DEPRECATED_WRITE = (
    "use `attachments` on create, `add_attachments` and "
    "`remove_attachments` on update"
)


class IssueLinkAttachment(IssueLink):
    """A link attachment, as read."""

    kind: Literal["link"]
    id: UUID
    """The attachment's id, which ``remove_attachments`` takes."""


class IssueFileAttachment(IssueFile):
    """A file attachment, as read."""

    kind: Literal["file"]
    id: UUID


class IssueEventAttachment(IssueEventReference):
    """An event attachment, as read."""

    kind: Literal["event"]
    id: UUID


class IssueSpanAttachment(IssueSpanReference):
    """A span attachment, as read."""

    kind: Literal["span"]
    id: UUID


class UnknownIssueAttachment(ApiModel):
    """An attachment of a ``kind`` this SDK version predates. Every field
    the server sent is kept as an extra."""

    kind: str
    id: UUID | None = None


IssueAttachment = Annotated[
    Annotated[IssueLinkAttachment, Tag("link")]
    | Annotated[IssueFileAttachment, Tag("file")]
    | Annotated[IssueEventAttachment, Tag("event")]
    | Annotated[IssueSpanAttachment, Tag("span")]
    | Annotated[UnknownIssueAttachment, Tag("unknown")],
    Discriminator(tag_or_unknown("kind", ATTACHMENT_KINDS)),
]
"""One piece of an issue's evidence, discriminated on ``kind``. Each has
its own ``id``; a kind this SDK does not know is an
:class:`UnknownIssueAttachment`."""


class IssueAttachmentCreateBase(RequestModel):
    """Always sends ``kind``, even under ``exclude_unset``."""

    def model_post_init(self, context: Any, /) -> None:
        self.model_fields_set.add("kind")


class IssueLinkAttachmentCreate(IssueLink, IssueAttachmentCreateBase):
    """A link to attach. The issue holds a ``url`` once."""

    kind: Literal["link"] = "link"


class IssueFileAttachmentCreate(IssueFile, IssueAttachmentCreateBase):
    """A Data Plane file to attach. The issue holds a ``file_id`` once."""

    kind: Literal["file"] = "file"


class IssueEventAttachmentCreate(
    IssueEventReference, IssueAttachmentCreateBase
):
    """A recorded event to attach. The issue holds an ``event_id`` once."""

    kind: Literal["event"] = "event"


class IssueSpanAttachmentCreate(IssueSpanReference, IssueAttachmentCreateBase):
    """A conversation span to attach. The issue holds a ``trace_id`` and
    ``span_id`` pair once."""

    kind: Literal["span"] = "span"


IssueAttachmentCreate = Annotated[
    IssueLinkAttachmentCreate
    | IssueFileAttachmentCreate
    | IssueEventAttachmentCreate
    | IssueSpanAttachmentCreate,
    Field(discriminator="kind"),
]
"""An attachment to add, without ``id``: the server assigns it, and skips
one whose identity the issue already holds."""


class IssueMember(ApiModel):
    """One person on an issue."""

    member_id: UUID
    relation: OpenIssueMemberRelation


class IssueComment(ApiModel):
    """One comment on an issue. Comments are append-only."""

    id: UUID
    """The comment's id, which is its event's id."""
    issue_id: UUID
    comment: str
    member_id: UUID | None = None
    """The member who commented."""
    actor_member_id: UUID | None = None
    """The member acting for ``member_id``, when delegated."""
    actor_member_type: str | None = None
    created_at: datetime


class Issue(ApiModel):
    """A stored issue: the brief, and each related list the read asked for.

    A list that was not included is ``None``.
    """

    id: UUID
    org_id: UUID
    project_id: UUID
    title: str
    description: str
    priority: OpenIssuePriority
    status: OpenIssueStatus
    revision: int
    tags: list[str]
    """Free-form tags, conventionally ``key:value``."""
    metadata: dict[str, IssueMetadataValue]
    display_index: int | None = None
    """Project-scoped display ID."""
    display_key: str | None = None
    """The display ID with the project's issue prefix, e.g. ``I-7``;
    ``None`` without a display index."""
    warnings: list[str] = Field(default_factory=list)
    """What this read left out, such as the comments beyond the include's
    cap."""
    task_id: UUID | None = None
    """The fixed worker Task that carries the issue's chat."""
    task_status: OpenTaskStatus | None = None
    """Current status of the worker Task."""
    member_id: UUID | None = None
    """Owning member of a private issue; ``None`` for a project-owned
    (Operator) issue."""
    created_by_member_id: UUID | None = None
    """``None`` when a caller that is not a member created the issue."""
    assignee_member_id: UUID | None = None
    reviewer_member_id: UUID | None = None
    closed_at: datetime | None = None
    """When the issue last entered ``closed`` or ``cancelled``."""
    members: list[IssueMember] | None = None
    """With ``include=members``: the creator, then the assignee, the
    reviewer, and the followers in the order they were added."""
    attachments: list[IssueAttachment] | None = None
    """With ``include=attachments``: the issue's evidence in the order it
    was added."""
    links: Annotated[
        list[IssueLink] | None, Field(deprecated=DEPRECATED_READ)
    ] = None
    """Deprecated: read ``attachments``."""
    files: Annotated[
        list[IssueFile] | None, Field(deprecated=DEPRECATED_READ)
    ] = None
    """Deprecated: read ``attachments``."""
    events: Annotated[
        list[IssueEventReference] | None, Field(deprecated=DEPRECATED_READ)
    ] = None
    """Deprecated: read ``attachments``."""
    spans: Annotated[
        list[IssueSpanReference] | None, Field(deprecated=DEPRECATED_READ)
    ] = None
    """Deprecated: read ``attachments``."""
    comments: list[IssueComment] | None = None
    """With ``include=comments`` on the single-issue read: oldest first, at
    most 500. Page the issue's events for more."""
    created_at: datetime
    updated_at: datetime

    @property
    def etag(self) -> str:
        """The issue's version as the server's ``ETag``: ``updated_at`` as
        ISO 8601 with its offset and full microsecond precision, quoted.
        Pass it as ``if_match`` to refuse a write if the issue changed
        since this read."""
        updated_at = self.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return f'"{updated_at.isoformat()}"'


class IssueEvidence(RequestModel):
    """The evidence and labels an issue's create and update bodies share.

    On an update each one replaces its list wholesale: ``[]`` clears it,
    ``{}`` clears ``metadata``. ``files``, ``links``, ``events`` and
    ``spans`` are deprecated: sending one with ``add_attachments`` or
    ``remove_attachments`` is refused with 422.
    """

    files: Annotated[
        list[IssueFile] | None, Field(deprecated=DEPRECATED_WRITE)
    ] = Field(default=None, max_length=200)
    """Deprecated: use attachments."""
    links: Annotated[
        list[IssueLink] | None, Field(deprecated=DEPRECATED_WRITE)
    ] = Field(default=None, max_length=200)
    """Deprecated: use attachments."""
    events: Annotated[
        list[IssueEventReference] | None, Field(deprecated=DEPRECATED_WRITE)
    ] = Field(default=None, max_length=50)
    """Deprecated: use attachments."""
    spans: Annotated[
        list[IssueSpanReference] | None, Field(deprecated=DEPRECATED_WRITE)
    ] = Field(default=None, max_length=50)
    """Deprecated: use attachments."""
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
    assignee_member_id: UUID | None = None
    reviewer_member_id: UUID | None = None
    follower_member_ids: list[UUID] | None = Field(default=None, max_length=50)
    attachments: list[IssueAttachmentCreate] | None = None
    """The issue's evidence, in order."""


class IssueUpdate(IssueEvidence):
    """Edit an issue's brief (``PATCH /v1/issues/{id}``).

    Only the fields you set are sent: ``tags``, ``metadata`` and the
    followers replace the stored ones wholesale (``[]`` or ``{}`` clears
    one). Evidence changes by ``add_attachments`` and
    ``remove_attachments``, which need no ``If-Match``. To refuse the edit if
    the issue changed since you read it, pass that read's
    :attr:`Issue.etag` as ``if_match``.
    """

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(
        default=None, min_length=1, max_length=50000
    )
    priority: IssuePriority | None = None
    status: IssueStatus | None = None
    assignee_member_id: UUID | None = None
    """Assigns, replacing the assignee; an explicit ``None`` unassigns."""
    reviewer_member_id: UUID | None = None
    """Sets, replacing the reviewer; an explicit ``None`` clears it."""
    follower_member_ids: list[UUID] | None = Field(default=None, max_length=50)
    """Replaces the followers wholesale; ``[]`` clears them."""
    add_attachments: list[IssueAttachmentCreate] | None = None
    """Appends, in order, the attachments the issue does not hold yet; one
    it holds already is skipped."""
    remove_attachments: list[UUID] | None = None
    """Removes the attachments with these ids; an id the issue does not
    hold is ignored."""


__all__ = [
    "Issue",
    "IssueAttachment",
    "IssueAttachmentCreate",
    "IssueComment",
    "IssueCreate",
    "IssueEvidence",
    "IssueEventAttachment",
    "IssueEventAttachmentCreate",
    "IssueEventReference",
    "IssueFileAttachment",
    "IssueFileAttachmentCreate",
    "IssueFile",
    "IssueInclude",
    "IssueLink",
    "IssueLinkAttachment",
    "IssueLinkAttachmentCreate",
    "IssueMember",
    "IssueMemberRelation",
    "IssueMetadataValue",
    "IssueOwner",
    "IssuePriority",
    "IssueSpanAttachment",
    "IssueSpanAttachmentCreate",
    "IssueSpanReference",
    "IssueStatus",
    "IssueStoredInclude",
    "IssueUpdate",
    "OpenIssueMemberRelation",
    "OpenIssuePriority",
    "OpenIssueStatus",
    "OpenTaskStatus",
    "UnknownIssueAttachment",
]
