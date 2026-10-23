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


__all__ = ["Project"]
