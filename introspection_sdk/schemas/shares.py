"""Pydantic mirrors of DP `/v1/shares` request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    model_validator,
)


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ShareResourceType(StrEnum):
    """Resource families a share grant can target (tasks are not shareable)."""

    FILE = "file"
    CONVERSATION = "conversation"
    ISSUE = "issue"
    CHANNEL = "channel"
    """A channel's audience. Written only by the control plane, so it can be
    read back from ``list`` but never passed to ``create``."""


class ShareMode(StrEnum):
    """What a share lets its grantees do."""

    READ = "read"
    WRITE = "write"
    """The resource's ordinary update, and adding file versions; never delete,
    tags, owner or shares. A conversation is shared ``read`` only."""


class UnsetType(Enum):
    """Type of :data:`UNSET`, the default of an argument whose ``None`` means
    "clear it" rather than "leave it alone"."""

    UNSET = "UNSET"


UNSET: Literal[UnsetType.UNSET] = UnsetType.UNSET


class ResourceShare(_ApiModel):
    """A sharing grant for a file, issue or conversation (`/v1/shares`).

    The grantee fields are ANDed: ``granted_member_id`` admits that member,
    ``granted_tag`` admits every caller whose token carries the tag, both
    admit that member only while they hold the tag, and neither is a
    project-wide grant."""

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    resource_type: ShareResourceType
    resource_id: str
    granted_member_id: UUID | None = None
    granted_tag: str | None = None
    mode: ShareMode = ShareMode.READ
    visible_from: datetime | None = None
    """Conversation shares only: spans before this instant stay hidden from
    callers the share alone admits."""
    created_by_member_id: UUID
    """Grantor (always a member) — the revoke gate."""
    url: str | None = None
    """Plain resource URL (``/v1/files/{id}``, ``/v1/issues/{id}`` or
    ``/v1/conversations/{id}/items``). Shares are ambient, so it carries no
    capability: the grantee reads the resource like any other."""


class ShareCreateRequest(_ApiModel):
    """Create a grant. Name a member, a tag, or both (ANDed); name neither for
    a project-wide grant. A tag share requires the grantor to hold the tag,
    unless they are an admin."""

    resource_type: ShareResourceType
    # A conversation id is not a uuid, so the wire type is a plain string.
    # A file id is one, though, and ``File.id`` hands back a ``UUID`` —
    # coercing here is what lets this SDK's own output be fed back into
    # its own input instead of raising a validation error.
    resource_id: Annotated[str, BeforeValidator(str)]
    granted_member_id: UUID | None = None
    granted_tag: str | None = None
    mode: ShareMode | None = None
    """``None`` takes the API default, ``read``."""
    visible_from: datetime | None = None
    """Conversation shares only; timezone-aware and not in the future."""


class ShareUpdateRequest(_ApiModel):
    """Change a grant's ``mode`` or ``visible_from``; the grantee is fixed.

    Only fields explicitly set go on the wire, so ``visible_from=None`` clears
    the cutoff while an omitted ``visible_from`` leaves it alone."""

    mode: ShareMode | None = None
    visible_from: datetime | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> ShareUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("a share update sets mode, visible_from or both")
        return self
