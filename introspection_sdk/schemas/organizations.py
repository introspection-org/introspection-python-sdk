"""Pydantic mirror of the CP ``/v1/organizations/me`` read model.

Unknown fields are ignored so CP additions don't break the SDK.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class Organization(BaseModel):
    """The organization the credential belongs to."""

    id: UUID
    name: str
    slug: str | None = None
    external_org_id: str | None = None
    """The identity provider's id for the organization."""
    image_url: str | None = None
    hosted_git: bool = True
    """Whether the organization's projects get hosted repositories."""


__all__ = ["Organization"]
