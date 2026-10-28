"""Pydantic mirrors of CP ``POST /v1/tokens``: a member's access token for
one project.

Unknown fields are tolerated via ``extra="allow"`` so CP additions don't
break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr


class ProjectTokenCreate(BaseModel):
    """Body of ``POST /v1/tokens``."""

    project: str
    expires_hours: int | None = None
    expires_minutes: int | None = None
    include_refresh_token: bool | None = None
    environment: str | None = None


class ProjectToken(BaseModel):
    """A project-scoped access token for the member who minted it, with that
    member's scopes on the project's Data Plane. Returned once."""

    model_config = ConfigDict(extra="allow")

    access_token: SecretStr
    token_type: str = "bearer"
    expires_at: datetime
    project_id: UUID
    org_id: UUID
    refresh_token: SecretStr | None = None
    """Only with ``include_refresh_token=True``."""


__all__ = ["ProjectToken", "ProjectTokenCreate"]
