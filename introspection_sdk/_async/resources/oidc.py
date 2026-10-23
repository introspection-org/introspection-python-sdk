"""Re-exported by :mod:`introspection_sdk.resources.oidc`."""

from __future__ import annotations

from introspection_sdk._async.resources._crud import _AsyncResource
from introspection_sdk.schemas.oidc import Me


class AsyncOidc(_AsyncResource):
    """CP ``/v1/oidc`` namespace: who the client's credential signs in as."""

    async def me(self) -> Me:
        """``GET /v1/oidc/me``: the member and org a member session or access
        token belongs to, with the org's resolved feature flags."""
        return await self._call("GET", "/v1/oidc/me", Me)
