"""Re-exported by :mod:`introspection_sdk.resources.organizations`."""

from __future__ import annotations

import logging

from introspection_sdk._async.resources._crud import _AsyncResource
from introspection_sdk.schemas.organizations import Organization

logger = logging.getLogger(__name__)


class AsyncOrganizations(_AsyncResource):
    """CP ``/v1/organizations`` namespace: the credential's own
    organization."""

    async def me(self) -> Organization:
        """``GET /v1/organizations/me``: the organization a member session or
        access token belongs to."""
        org = await self._call("GET", "/v1/organizations/me", Organization)
        logger.debug("organization read", extra={"org_id": str(org.id)})
        return org
