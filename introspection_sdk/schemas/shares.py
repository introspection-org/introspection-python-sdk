"""Pydantic mirrors of DP `/v1/shares` request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ShareResourceType(StrEnum):
    """Resource families a share grant can target (tasks are not shareable)."""

    FILE = "file"
    CONVERSATION = "conversation"


class ResourceShare(_ApiModel):
    """A read-sharing grant for a file or conversation (`/v1/shares`)."""

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    resource_type: ShareResourceType
    resource_id: str
    granted_member_id: UUID | None = None
    """Member-targeted grant; ``None`` means a project-wide grant (everyone)."""
    created_by_member_id: UUID
    """Grantor (always a member) — the revoke gate."""
    url: str
    """Fully-qualified GET URL for the shared resource, carrying the ``?share_id``
    capability (e.g. ``…/v1/files/{id}?share_id=…``). Always present on
    ``/v1/shares`` reads."""


class ShareCreateRequest(_ApiModel):
    """Create a grant. Omit ``granted_member_id`` for a project-wide grant; set
    it to target one member."""

    resource_type: ShareResourceType
    resource_id: str
    granted_member_id: UUID | None = None
