"""Async twins re-exported by :mod:`introspection_sdk.runner_resources.shares`."""

from __future__ import annotations

from datetime import datetime

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.runner_resources._shares_common import (
    _create_body,
    _list_params,
    _update_body,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.shares import (
    ResourceShare,
    ShareResourceType,
)


class AsyncShares:
    """Asynchronous `/v1/shares` resource."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        resource_type: ShareResourceType | str | None = None,
        resource_id: str | None = None,
        granted_member_id: str | None = None,
        granted_tag: str | None = None,
        created_by_me: bool = False,
        granted_to_me: bool = False,
    ) -> AsyncPager[ResourceShare, Paginated[ResourceShare]]:
        """List grants the caller created or that name them.

        ``granted_to_me`` matches grants naming the caller's member, a tag the
        caller's token carries, or both."""

        async def fetch(cursor: str | None) -> Paginated[ResourceShare]:
            payload = await self._http.request(
                "GET",
                "/v1/shares",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    granted_member_id=granted_member_id,
                    granted_tag=granted_tag,
                    created_by_me=created_by_me,
                    granted_to_me=granted_to_me,
                ),
            )
            return Paginated[ResourceShare].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        resource_type: ShareResourceType | str,
        resource_id: str,
        granted_member_id: str | None = None,
        granted_tag: str | None = None,
        visible_from: datetime | None = None,
    ) -> ResourceShare:
        """Create a grant. The caller must own the target resource.

        ``granted_member_id`` and ``granted_tag`` are ANDed; omit both for a
        project-wide grant. A tag share also requires the caller to hold the
        tag (or be an admin), and a duplicate live tag share raises
        ``ConflictError``. A share admits; the grantee's token scopes decide
        whether they may read, write or delete. ``visible_from``
        (conversations only, timezone-aware, not in the future) hides earlier
        spans from callers the share alone admits."""
        payload = await self._http.request(
            "POST",
            "/v1/shares",
            json=_create_body(
                resource_type=resource_type,
                resource_id=resource_id,
                granted_member_id=granted_member_id,
                granted_tag=granted_tag,
                visible_from=visible_from,
            ),
        )
        return ResourceShare.model_validate(payload)

    async def get(self, share_id: str) -> ResourceShare:
        payload = await self._http.request("GET", f"/v1/shares/{share_id}")
        return ResourceShare.model_validate(payload)

    async def update(
        self,
        share_id: str,
        *,
        visible_from: datetime | None,
    ) -> ResourceShare:
        """Set or clear a conversation grant's ``visible_from``.

        ``visible_from=None`` clears the cutoff. The grantee cannot change;
        revoke and create another to admit someone else. Only the grantor or
        an admin may update a grant; anyone else gets ``NotFoundError``, and a
        non-conversation share is a ``422``."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/shares/{share_id}",
            json=_update_body(visible_from),
        )
        return ResourceShare.model_validate(payload)

    async def delete(self, share_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/shares/{share_id}", expect="empty"
        )
