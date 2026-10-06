"""Pydantic mirrors of DP ``/v1/connections`` request/response models.

These are a member's app connections on the data plane. A connector's
connections on the control plane are
:class:`introspection_sdk.schemas.connectors.Connection`, a different model.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Connection(_ApiModel):
    """One app a member connected for themself."""

    id: UUID
    member_id: UUID
    app: str
    """Provider application slug, such as ``gmail``."""
    account_name: str | None = None
    """The provider account the app is connected as, when the provider
    names one."""
    healthy: bool
    """False when the provider no longer accepts the connection; connect
    the app again."""
    created_at: datetime


class ConnectionCreateRequest(_ApiModel):
    """Body for ``POST /v1/connections``."""

    app: str
    runtime: str


class ConnectPage(_ApiModel):
    """A single-use connect page for one app. Open it in a browser and never
    cache it; it ends on a page saying the app is connected."""

    authorize_url: str
    expires_in: int
    """Seconds until the page stops working."""
    expires_at: datetime | None = None
