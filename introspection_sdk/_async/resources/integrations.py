"""Re-exported by :mod:`introspection_sdk.resources.integrations`."""

from __future__ import annotations

from uuid import UUID

from pydantic import SecretStr

from introspection_sdk._async.resources._crud import _AsyncResource, _body
from introspection_sdk.pagination import AsyncPager
from introspection_sdk.schemas.integrations import (
    Integration,
    IntegrationCreateRequest,
    IntegrationStatus,
    IntegrationType,
    IntegrationUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated


def _integration_path(integration_id: UUID) -> str:
    return f"/v1/integrations/{integration_id}"


class AsyncIntegrations(_AsyncResource):
    """CP ``/v1/integrations`` namespace: the org's own provider installs.

    Org-wide, so no project selector. A create returns a ``pending`` row (or
    the live pending one of that type: there is at most one live integration
    per type), which the provider's activation flow completes with an
    update. Needs an org credential.
    """

    def list(
        self, *, limit: int | None = None, next: str | None = None
    ) -> AsyncPager[Integration, Paginated[Integration]]:
        """List the org's integrations, across pages."""
        return self._paginate(
            "/v1/integrations",
            Paginated[Integration],
            {"limit": limit, "next": next},
        )

    async def get(self, integration_id: UUID) -> Integration:
        return await self._call(
            "GET", _integration_path(integration_id), Integration
        )

    async def create(
        self,
        *,
        integration_type: IntegrationType | str,
        name: str | None = None,
        external_id: str | None = None,
    ) -> Integration:
        """Record an install, sent as the wire field ``type``. Raises
        :class:`~introspection_sdk.ConflictError` when an active or disabled
        integration of the type already exists."""
        body = _body(
            IntegrationCreateRequest,
            {
                "type": integration_type,
                "name": name,
                "external_id": external_id,
            },
        )
        return await self._call(
            "POST", "/v1/integrations", Integration, json=body
        )

    async def update(
        self,
        integration_id: UUID,
        *,
        name: str | None = None,
        status: IntegrationStatus | str | None = None,
        external_id: str | None = None,
        code: str | SecretStr | None = None,
        redirect_uri: str | None = None,
        slack_interactivity_enabled: bool | None = None,
    ) -> Integration:
        """Only given fields change. ``code`` and ``redirect_uri`` complete a
        provider's OAuth activation; ``slack_interactivity_enabled`` accepts
        only ``False``."""
        body = _body(
            IntegrationUpdateRequest,
            {
                "name": name,
                "status": status,
                "external_id": external_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "slack_interactivity_enabled": slack_interactivity_enabled,
            },
        )
        return await self._call(
            "PATCH", _integration_path(integration_id), Integration, json=body
        )

    async def delete(self, integration_id: UUID) -> None:
        await self._delete(_integration_path(integration_id))
