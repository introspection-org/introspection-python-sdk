"""Pydantic mirrors of CP `/v1/recipes` response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Recipe(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    repository_id: UUID
    name: str
    slug: str
    git_ref: str
    git_commit_sha: str
    sub_path: str | None = None
    description: str | None = None
    created_by_member_id: UUID
    created_at: datetime
    updated_at: datetime


class RecipeCreate(BaseModel):
    """Body of ``POST /v1/recipes``: a recipe pinned to one commit of a
    repository."""

    project: str
    name: str
    repository_id: UUID | None = None
    git_ref: str | None = None
    git_commit_sha: str | None = None
    git_commit_subject: str | None = None
    sub_path: str | None = None
    slug: str | None = None
    description: str | None = None


class RecipeUpdate(BaseModel):
    """Body of ``PATCH /v1/recipes/{id}``; an unset field is left as is."""

    name: str | None = None
    description: str | None = None


__all__ = ["Recipe", "RecipeCreate", "RecipeUpdate"]
