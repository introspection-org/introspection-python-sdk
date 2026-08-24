"""Pydantic mirrors of DP `/v1/datasets` request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_LabelPredicate = Annotated[list[str], Field(min_length=1)]


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Dataset(_ApiModel):
    """A named label predicate over annotations (`/v1/datasets`).

    A dataset is a saved filter, not a membership: ``labels`` is the
    predicate, and listing annotations with ``dataset_id`` applies it.
    """

    id: UUID
    org_id: UUID
    project_id: UUID
    slug: str
    description: str | None = None
    labels: _LabelPredicate
    created_by_member_id: UUID
    created_at: datetime
    updated_at: datetime


class DatasetCreateRequest(_ApiModel):
    """Create a dataset. The server slugifies ``slug`` and normalizes
    ``labels`` (at least one required — it is the saved predicate);
    create is idempotent on the live slug (a repeat POST returns the
    existing row)."""

    slug: str
    description: str | None = None
    labels: _LabelPredicate


class DatasetUpdateRequest(_ApiModel):
    """All-optional PATCH body; ``labels`` must keep at least one
    entry when present."""

    description: str | None = None
    labels: _LabelPredicate | None = None
