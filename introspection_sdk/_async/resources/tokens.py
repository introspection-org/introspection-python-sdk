"""Re-exported by :mod:`introspection_sdk.resources.tokens`."""

from __future__ import annotations

import logging
from uuid import UUID

from introspection_sdk._async.resources._crud import _AsyncResource, _body
from introspection_sdk.schemas.tokens import ProjectToken, ProjectTokenCreate

logger = logging.getLogger(__name__)


class AsyncTokens(_AsyncResource):
    """CP ``/v1/tokens`` namespace: a signed-in member's access token for
    one project."""

    async def create(
        self,
        *,
        project: str | UUID,
        expires_hours: int | None = None,
        expires_minutes: int | None = None,
        include_refresh_token: bool | None = None,
        environment: str | None = None,
    ) -> ProjectToken:
        """Mint an access token for ``project`` (slug or id) carrying the
        caller's own scopes there, such as ``git:push``, which no service
        account holds. ``environment`` binds it to one lane."""
        body = _body(
            ProjectTokenCreate,
            {
                "project": str(project),
                "expires_hours": expires_hours,
                "expires_minutes": expires_minutes,
                "include_refresh_token": include_refresh_token,
                "environment": environment,
            },
        )
        token = await self._call("POST", "/v1/tokens", ProjectToken, json=body)
        logger.debug(
            "project token minted",
            extra={
                "project_id": str(token.project_id),
                "environment": environment,
            },
        )
        return token
