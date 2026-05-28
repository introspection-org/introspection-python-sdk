"""Pydantic mirrors of CP `/v1/runtimes` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Runtime(_ApiModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    recipe_id: UUID | None = None
    is_active: bool = False
    description: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuntimeCreate(_ApiModel):
    project_id: UUID
    name: str
    recipe_id: UUID | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


class RuntimeUpdate(_ApiModel):
    name: str | None = None
    recipe_id: UUID | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


__all__ = ["Runtime", "RuntimeCreate", "RuntimeUpdate"]
