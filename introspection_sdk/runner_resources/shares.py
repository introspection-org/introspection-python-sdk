"""`runner.shares.*` namespace: read-sharing grants for files and conversations.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets the
runner's DP endpoint with its short-lived JWT. ``create`` / ``list`` / ``get`` /
``delete`` manage grants. A grant carries a ``url`` (with the ``?share_id``
capability) for reading the shared resource. To fork a new task from a shared
conversation, pass ``fork_share_id`` to ``runner.tasks.create(...)``.
"""

from __future__ import annotations

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
    ResourceShare,
    ShareCreateRequest,
    ShareResourceType,
)


def _list_params(
    *,
    limit: int,
    cursor: str | None,
    resource_type: ShareResourceType | str | None,
    resource_id: str | None,
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
        "created_by_me": created_by_me,
        "granted_to_me": granted_to_me,
    }


def _create_body(
    *,
    resource_type: ShareResourceType | str,
    resource_id: str,
    granted_member_id: str | None,
) -> dict[str, Any]:
    # Loose public inputs (plain str / enum) are coerced by validation:
    # str -> ShareResourceType, str -> UUID for granted_member_id.
    return ShareCreateRequest.model_validate(
        {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "granted_member_id": granted_member_id,
        }
    ).model_dump(mode="json", exclude_none=True)


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
        created_by_me: bool = False,
        granted_to_me: bool = False,
    ) -> Pager[ResourceShare, Paginated[ResourceShare]]:
        """List grants the caller created or that target them."""

        def fetch(cursor: str | None) -> Paginated[ResourceShare]:
            payload = self._http.request(
                "GET",
                "/v1/shares",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    resource_type=resource_type,
                    resource_id=resource_id,
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
    ) -> ResourceShare:
        """Create a grant. The caller must own the target resource."""
        payload = self._http.request(
            "POST",
            "/v1/shares",
            json=_create_body(
                resource_type=resource_type,
                resource_id=resource_id,
                granted_member_id=granted_member_id,
            ),
        )
        return ResourceShare.model_validate(payload)

    def get(self, share_id: str) -> ResourceShare:
        payload = self._http.request("GET", f"/v1/shares/{share_id}")
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
        created_by_me: bool = False,
        granted_to_me: bool = False,
    ) -> AsyncPager[ResourceShare, Paginated[ResourceShare]]:
        """List grants the caller created or that target them."""

        async def fetch(cursor: str | None) -> Paginated[ResourceShare]:
            payload = await self._http.request(
                "GET",
                "/v1/shares",
                params=_list_params(
                    limit=limit,
                    cursor=cursor,
                    resource_type=resource_type,
                    resource_id=resource_id,
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
    ) -> ResourceShare:
        """Create a grant. The caller must own the target resource."""
        payload = await self._http.request(
            "POST",
            "/v1/shares",
            json=_create_body(
                resource_type=resource_type,
                resource_id=resource_id,
                granted_member_id=granted_member_id,
            ),
        )
        return ResourceShare.model_validate(payload)

    async def get(self, share_id: str) -> ResourceShare:
        payload = await self._http.request("GET", f"/v1/shares/{share_id}")
        return ResourceShare.model_validate(payload)

    async def delete(self, share_id: str) -> None:
        await self._http.request(
            "DELETE", f"/v1/shares/{share_id}", expect="empty"
        )
