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


class ShareVisibilityLevel(StrEnum):
    PROJECT = "project"


class ResourceShare(_ApiModel):
    """A read-sharing grant for a file or conversation (`/v1/shares`)."""

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    resource_type: ShareResourceType
    resource_id: str
    visibility_level: ShareVisibilityLevel | None = None
    granted_member_id: UUID | None = None
    created_by_member_id: UUID | None = None
    url: str | None = None
    """Fully-qualified GET URL for the shared resource, carrying the
    ``?share_id`` capability (e.g. ``…/v1/files/{id}?share_id=…``)."""


class ShareCreateRequest(_ApiModel):
    """Create a grant — exactly one of ``visibility_level`` /
    ``granted_member_id`` must be set."""

    resource_type: ShareResourceType
    resource_id: str
    visibility_level: ShareVisibilityLevel | None = None
    granted_member_id: UUID | None = None
