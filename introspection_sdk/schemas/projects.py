"""Pydantic mirror of the CP ``/v1/projects`` read model.

Unknown fields are tolerated via ``extra="allow"`` so CP additions don't
break the SDK.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Project(BaseModel):
    """A project of the credential's organization."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    deployment_id: UUID
    """The Data Plane deployment the project lives on."""
    name: str
    slug: str | None = None
    """The stable identifier the CLI and dashboard URLs use. A project
    created before slugs existed may have none."""
    description: str | None = None
    settings: dict[str, Any] | None = None
    created_by_member_id: UUID | None = None


class ProjectCreate(BaseModel):
    """Body of ``POST /v1/projects``."""

    name: str
    deployment_id: UUID
    """The Data Plane deployment the project lives on."""
    slug: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    include_ark: bool | None = None
    """Seed the Ark runtime. Unset, an organization's first project takes it
    and later ones do not."""


class ProjectUpdate(BaseModel):
    """Body of ``PATCH /v1/projects/{project}``; an unset field is left as
    is."""

    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None


__all__ = ["Project", "ProjectCreate", "ProjectUpdate"]
