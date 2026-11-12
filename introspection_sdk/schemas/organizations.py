"""Pydantic mirror of the CP ``/v1/organizations/me`` read model.

Unknown fields are tolerated via ``extra="allow"`` so CP additions don't
break the SDK.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PasskeyRequirement(StrEnum):
    """When the organization's members must sign in with a passkey."""

    OFF = "off"
    ALWAYS = "always"
    EXCEPT_SSO = "except_sso"


OpenPasskeyRequirement = Annotated[
    PasskeyRequirement | str, Field(union_mode="left_to_right")
]


class SignInSettings(BaseModel):
    """How the organization's members sign in and who can be invited."""

    model_config = ConfigDict(extra="allow")

    passkey_requirement: OpenPasskeyRequirement = PasskeyRequirement.OFF
    restrict_invites_to_domains: bool = False


class Organization(BaseModel):
    """The organization the credential belongs to."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    name: str
    slug: str | None = None
    external_org_id: str | None = None
    """The identity provider's id for the organization."""
    image_url: str | None = None
    hosted_git: bool = True
    """Whether the organization's projects get hosted repositories."""
    sign_in: SignInSettings | None = None
    """Present only where the organization has Enterprise sign-in."""
    subscription_live: bool | None = None
    """Whether the subscription is paid and grants the organization's roles
    their full scopes; ``None`` from a server that does not say."""


__all__ = [
    "OpenPasskeyRequirement",
    "Organization",
    "PasskeyRequirement",
    "SignInSettings",
]
