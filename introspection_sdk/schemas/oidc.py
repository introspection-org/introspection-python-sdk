"""Pydantic mirror of CP ``GET /v1/oidc/me``."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

FeatureFlagValue = bool | int | float | str
"""A feature flag's resolved value."""


class Me(BaseModel):
    """Who the credential is: the member and org a member session or access
    token belongs to, with the org's resolved feature flags."""

    model_config = ConfigDict(extra="allow")

    authenticated: bool = True
    org_id: UUID | None = None
    member_id: UUID | None = None
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    feature_flags: dict[str, FeatureFlagValue] = {}
    impersonating_member_id: UUID | None = None
    """Set while an operator impersonates this member."""
    impersonator_email: str | None = None


__all__ = ["FeatureFlagValue", "Me"]
