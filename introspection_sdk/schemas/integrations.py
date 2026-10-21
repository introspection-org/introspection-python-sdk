"""Pydantic mirrors of CP ``/v1/integrations`` request/response models.

An integration is the org's own install of a provider (a GitHub App
installation, a Slack workspace): org-wide, at most one live per type. The
wire field naming the provider is ``type``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from introspection_sdk.schemas._secrets import WireSecret


class IntegrationType(StrEnum):
    GITHUB = "github"
    SLACK = "slack"
    LINEAR = "linear"
    JIRA = "jira"
    NOTION = "notion"
    VERCEL = "vercel"
    CUSTOM = "custom"


class IntegrationStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class Integration(BaseModel):
    """An org-wide provider install."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    type: IntegrationType
    name: str | None = None
    external_id: str | None = None
    """The provider's id for the install, set once it is activated."""
    status: IntegrationStatus = IntegrationStatus.PENDING
    created_by_member_id: UUID
    token_expires_at: datetime | None = None
    data: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class IntegrationCreateRequest(BaseModel):
    """Body of ``POST /v1/integrations``. The row is always created
    ``pending``; the provider's activation flow completes it with an
    update."""

    model_config = ConfigDict(extra="forbid")

    type: IntegrationType
    name: str | None = None
    external_id: str | None = None


class IntegrationUpdateRequest(BaseModel):
    """Body of ``PATCH /v1/integrations/{id}``. ``code`` and
    ``redirect_uri`` complete a provider's OAuth activation."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    status: IntegrationStatus | None = None
    external_id: str | None = None
    code: WireSecret | None = None
    redirect_uri: str | None = None
    slack_interactivity_enabled: bool | None = None
    """Only ``False`` is accepted: turns Slack interactivity off."""


__all__ = [
    "Integration",
    "IntegrationCreateRequest",
    "IntegrationStatus",
    "IntegrationType",
    "IntegrationUpdateRequest",
]
