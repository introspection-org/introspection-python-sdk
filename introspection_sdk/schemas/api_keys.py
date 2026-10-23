"""Pydantic mirrors of CP ``/v1/api-keys`` request/response models.

A key's plaintext is returned once, on create, as :attr:`ApiKeyCreated.api_key`
(a :class:`~pydantic.SecretStr`, so it never prints); no read returns it again.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr

from introspection_sdk.schemas.lanes import Environment


class ApiKeyCapability(StrEnum):
    """What a project API key may do beyond the runner set."""

    RUNTIMES = "runtimes"
    EVALS = "evals"


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    ROTATING = "rotating"
    """Deleted with a grace period: still valid until ``expires_at``."""
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApiKey(BaseModel):
    """A project API key. The plaintext is never readable after create."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    org_id: UUID
    project_id: UUID
    created_at: datetime | None = None
    name: str | None = None
    environment: Environment = Environment.PRODUCTION
    allow: list[ApiKeyCapability] = []
    scope: str = "*"
    member_id: UUID | None = None
    """The agent member the key acts as, when it is not the default one."""
    key_prefix: str
    key_suffix: str
    redacted_key: str | None = None
    status: ApiKeyStatus = ApiKeyStatus.ACTIVE
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    acknowledged_at: datetime | None = None
    """Set once ``api_keys.acknowledge`` records the key as saved."""
    key_display: str
    prefix: str


class ApiKeyCreated(ApiKey):
    """Response of ``POST /v1/api-keys``: the key plus its plaintext, the
    only time the API returns it."""

    api_key: SecretStr | None = None


class ApiKeyCreateRequest(BaseModel):
    """Body of ``POST /v1/api-keys``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    environment: Environment | None = None
    """Defaults to ``production`` server-side."""
    allow: list[ApiKeyCapability] | None = None
    member_id: UUID | None = None
    """Act as this external-credential agent rather than the default one."""
    expires_at: datetime | None = None


class ApiKeyUpdateRequest(BaseModel):
    """Body of ``PATCH /v1/api-keys/{id}``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    allow: list[ApiKeyCapability] | None = None
    member_id: UUID | None = None


class ApiKeyAcknowledgement(BaseModel):
    """Response of ``POST /v1/api-keys/{id}/acknowledge``."""

    model_config = ConfigDict(extra="allow")

    acknowledged: bool


__all__ = [
    "ApiKey",
    "ApiKeyAcknowledgement",
    "ApiKeyCapability",
    "ApiKeyCreateRequest",
    "ApiKeyCreated",
    "ApiKeyStatus",
    "ApiKeyUpdateRequest",
]
