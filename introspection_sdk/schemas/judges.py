"""Pydantic mirrors of CP ``/v1/judges`` request/response models.

A judge is authored in its Recipe and published with it, so the API has no
create or delete; an update changes only ``enabled`` and ``sample_rate``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Judge(BaseModel):
    """A judge a Recipe declares."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    project_id: UUID
    runtime_group_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    name: str
    description: str | None = None
    enabled: bool = True
    sample_rate: float = 1.0
    source: str = "recipe"
    repository_id: UUID | None = None
    recipe_git_commit_sha: str | None = None
    source_path: str | None = None
    definition_hash: str
    created_by_member_id: UUID | None = None


class JudgeUpdateRequest(BaseModel):
    """Body of ``PATCH /v1/judges/{id}``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    """The fraction of conversations judged, ``0.0``–``1.0``."""


__all__ = ["Judge", "JudgeUpdateRequest"]
