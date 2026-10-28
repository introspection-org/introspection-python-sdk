"""Re-exported by :mod:`introspection_sdk.resources.organizations`."""

from __future__ import annotations

from introspection_sdk._async.resources._crud import _AsyncResource
from introspection_sdk.schemas.organizations import Organization


class AsyncOrganizations(_AsyncResource):
    """CP ``/v1/organizations`` namespace: the credential's own
    organization."""

    async def me(self) -> Organization:
        """``GET /v1/organizations/me``: the organization a member session or
        access token belongs to."""
        return await self._call("GET", "/v1/organizations/me", Organization)
