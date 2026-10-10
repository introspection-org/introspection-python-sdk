"""`runner.shares.*` namespace: sharing grants for files, issues and conversations.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets the
runner's DP endpoint with its short-lived JWT. ``create`` / ``list`` / ``get`` /
``update`` / ``delete`` manage grants. Shares are ambient: a shared resource
appears in the grantee's ordinary reads, and a grant's ``url`` is the plain
resource URL. To share with a cohort, create a share with ``granted_tag``. To
fork a new task from a shared conversation, pass ``fork_share_id`` to
``runner.tasks.create(...)``; the API refuses one whose share has
``visible_from`` set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.shares import (
    UNSET,
    ResourceShare,
    ShareCreateRequest,
    ShareMode,
    ShareResourceType,
    ShareUpdateRequest,
    UnsetType,
)


def _list_params(
    *,
    limit: int,
    cursor: str | None,
    resource_type: ShareResourceType | str | None,
    resource_id: str | None,
    granted_member_id: str | None,
    granted_tag: str | None,
    created_by_me: bool,
    granted_to_me: bool,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "next": cursor,
        "resource_type": (
            resource_type.value
            if isinstance(resource_type, ShareResourceType)
            else resource_type
        ),
        "resource_id": resource_id,
        "granted_member_id": granted_member_id,
        "granted_tag": granted_tag,
        "created_by_me": created_by_me,
        "granted_to_me": granted_to_me,
    }


def _create_body(
    *,
    resource_type: ShareResourceType | str,
    resource_id: str,
    granted_member_id: str | None,
    granted_tag: str | None,
    mode: ShareMode | str | None,
    visible_from: datetime | None,
) -> dict[str, Any]:
    # Loose public inputs (plain str / enum) are coerced by validation:
    # str -> ShareResourceType, str -> UUID for granted_member_id.
    return ShareCreateRequest.model_validate(
        {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "granted_member_id": granted_member_id,
            "granted_tag": granted_tag,
            "mode": mode,
            "visible_from": visible_from,
        }
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    mode: ShareMode | str | None,
    visible_from: datetime | None | UnsetType,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if mode is not None:
        fields["mode"] = mode
    if visible_from is not UNSET:
        fields["visible_from"] = visible_from
    return ShareUpdateRequest.model_validate(fields).model_dump(
        mode="json", exclude_unset=True
    )


class Shares:
    """Synchronous `/v1/shares` resource."""

    def __init__(self, http: _HttpClient) -> None:
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
    ) -> Pager[ResourceShare, Paginated[ResourceShare]]:
        """List grants the caller created or that name them.

        ``granted_to_me`` matches grants naming the caller's member, a tag the
        caller's token carries, or both."""

        def fetch(cursor: str | None) -> Paginated[ResourceShare]:
            payload = self._http.request(
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

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        resource_type: ShareResourceType | str,
        resource_id: str,
        granted_member_id: str | None = None,
        granted_tag: str | None = None,
        mode: ShareMode | str | None = None,
        visible_from: datetime | None = None,
    ) -> ResourceShare:
        """Create a grant. The caller must own the target resource.

        ``granted_member_id`` and ``granted_tag`` are ANDed; omit both for a
        project-wide grant. A tag share also requires the caller to hold the
        tag (or be an admin), and a duplicate live tag share raises
        ``ConflictError``. ``mode`` defaults to ``read`` and must be ``read``
        for a conversation; ``visible_from`` (conversations only, timezone-aware,
        not in the future) hides earlier spans from callers the share alone
        admits."""
        payload = self._http.request(
            "POST",
            "/v1/shares",
            json=_create_body(
                resource_type=resource_type,
                resource_id=resource_id,
                granted_member_id=granted_member_id,
                granted_tag=granted_tag,
                mode=mode,
                visible_from=visible_from,
            ),
        )
        return ResourceShare.model_validate(payload)

    def get(self, share_id: str) -> ResourceShare:
        payload = self._http.request("GET", f"/v1/shares/{share_id}")
        return ResourceShare.model_validate(payload)

    def update(
        self,
        share_id: str,
        *,
        mode: ShareMode | str | None = None,
        visible_from: datetime | None | UnsetType = UNSET,
    ) -> ResourceShare:
        """Change a grant's ``mode`` or ``visible_from``; pass at least one.

        ``visible_from=None`` clears the cutoff; omitting it leaves it alone.
        The grantee cannot change. Only the grantor or an admin may update a
        grant; anyone else gets ``NotFoundError``."""
        payload = self._http.request(
            "PATCH",
            f"/v1/shares/{share_id}",
            json=_update_body(mode=mode, visible_from=visible_from),
        )
        return ResourceShare.model_validate(payload)

    def delete(self, share_id: str) -> None:
        self._http.request("DELETE", f"/v1/shares/{share_id}", expect="empty")


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
        mode: ShareMode | str | None = None,
        visible_from: datetime | None = None,
    ) -> ResourceShare:
        """Create a grant. The caller must own the target resource.

        ``granted_member_id`` and ``granted_tag`` are ANDed; omit both for a
        project-wide grant. A tag share also requires the caller to hold the
        tag (or be an admin), and a duplicate live tag share raises
        ``ConflictError``. ``mode`` defaults to ``read`` and must be ``read``
        for a conversation; ``visible_from`` (conversations only, timezone-aware,
        not in the future) hides earlier spans from callers the share alone
        admits."""
        payload = await self._http.request(
            "POST",
            "/v1/shares",
            json=_create_body(
                resource_type=resource_type,
                resource_id=resource_id,
                granted_member_id=granted_member_id,
                granted_tag=granted_tag,
                mode=mode,
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
        mode: ShareMode | str | None = None,
        visible_from: datetime | None | UnsetType = UNSET,
    ) -> ResourceShare:
        """Async twin of :meth:`Shares.update`."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/shares/{share_id}",
            json=_update_body(mode=mode, visible_from=visible_from),
        )
        return ResourceShare.model_validate(payload)

    async def delete(self, share_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/shares/{share_id}", expect="empty"
        )
