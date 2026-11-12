"""Pydantic mirrors of DP ``/v1/connections`` request/response models.

These are the connections on the data plane: an app a member connected,
a member's own account through an organization integration, or the
project's own account on a connector.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ConnectionOwner(StrEnum):
    """Whose grant a connection is."""

    MEMBER = "member"
    PROJECT = "project"


class ConnectorRef(ApiModel):
    """The connector a connection is on, as the project sees it."""

    id: UUID
    slug: str
    provider: str
    peering: str | None = None
    """The peering the project reaches the connector through, if any."""


class Connection(ApiModel):
    """One connection: an app a member connected for themself, a member's
    own account through an organization integration, or the project's own
    account on a connector."""

    id: UUID
    owner: ConnectionOwner | str = ConnectionOwner.MEMBER
    member_id: UUID | None = None
    """The member whose grant this is; ``None`` for the project's own."""
    connector: ConnectorRef | None = None
    """The connector it is on; ``None`` for an integration's."""
    integration_id: UUID | None = None
    """The organization integration it is through; ``None`` for a
    connector's."""
    runtime_group_id: UUID | None = None
    """The runtime group whose channels it answers, if any."""
    subject_type: str | None = None
    app: str
    """Provider application slug, such as ``gmail``, the connector's slug,
    or the integration's type."""
    provider_account_id: str | None = None
    """The provider's id for the account, such as ``apn_...``."""
    account_name: str | None = None
    """The provider account the app is connected as, when the provider
    names one."""
    healthy: bool
    """False when the provider no longer accepts the connection; connect
    the app again."""
    status: str | None = None
    token_expires_at: datetime | None = None
    """When the access token expires, if it does."""
    last_verified_at: datetime | None = None
    created_by_member_id: UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ConnectionCreateRequest(ApiModel):
    """Body for ``POST /v1/connections``: ``app`` with ``runtime``, or
    ``integration_id``."""

    integration_id: UUID | None = None
    app: str | None = None
    runtime: str | None = None
    return_url: str | None = None


class ConnectPage(ApiModel):
    """A single-use connect page for one app. Open it in a browser and never
    cache it; it ends on a page saying the app is connected."""

    authorize_url: str
    expires_in: int
    """Seconds until the page stops working."""
    expires_at: datetime | None = None


__all__ = [
    "ApiModel",
    "ConnectPage",
    "Connection",
    "ConnectionCreateRequest",
    "ConnectionOwner",
    "ConnectorRef",
]
