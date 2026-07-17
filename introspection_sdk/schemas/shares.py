"""Pydantic mirrors of DP `/v1/shares` request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    """Member target; ``None`` also covers identity/project-wide grants."""
    granted_identity_key: str | None = None
    created_by_member_id: UUID
    """Grantor (always a member) — the revoke gate."""
    created_by_identity_key: str | None = None
    url: str | None = None
    """Canonical resource URL, populated by the API on share reads."""


class ShareCreateRequest(_ApiModel):
    """Create a grant. Omit ``granted_member_id`` for a project-wide grant; set
    it to target one member."""

    resource_type: ShareResourceType
    resource_id: str
    granted_member_id: UUID | None = None
    granted_identity_key: str | None = Field(
        default=None, min_length=1, max_length=320
    )

    @model_validator(mode="after")
    def _one_target(self) -> ShareCreateRequest:
        if (
            self.granted_member_id is not None
            and self.granted_identity_key is not None
        ):
            raise ValueError(
                "a grant targets a member or an identity, not both"
            )
        return self
