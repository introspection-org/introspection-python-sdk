"""Pydantic mirrors of DP `/v1/datasets` request/response models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Dataset(_ApiModel):
    """A named annotation collection (`/v1/datasets`).

    Membership rides annotations: an annotation row's ``dataset_id``
    is what places a conversation in a dataset.
    """

    id: UUID
    org_id: UUID
    project_id: UUID
    slug: str
    description: str | None = None
    created_by_member_id: UUID
    created_at: datetime
    updated_at: datetime


class DatasetCreateRequest(_ApiModel):
    """Create a dataset. The server slugifies ``slug``; create is
    idempotent on the live slug (a repeat POST returns the existing
    row)."""

    slug: str
    description: str | None = None


class DatasetUpdateRequest(_ApiModel):
    """All-optional PATCH body."""

    description: str | None = None
