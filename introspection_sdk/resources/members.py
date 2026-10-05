"""``client.members`` — CP namespace for ``/v1/members``.

Members are the organization's principals: ``business`` humans,
``agent`` members, and ``customer`` members minted from an asserted
identity (:class:`~introspection_sdk.schemas.runner.RunnerIdentity`).
``create`` invites a human by email; ``customer`` members are never
created here, only by identity assertion.

Reads need ``members:read``. ``update`` needs ``members:manage`` (owner),
as does seeding ``tags`` on ``create``: a member tag is access-bearing.
``metadata`` grants nothing.
"""

from __future__ import annotations

import builtins
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.members import (
    Member,
    MemberCreateRequest,
    MemberType,
    MemberUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated


def _list_params(
    *,
    project: str | UUID | None,
    member_type: MemberType | str | None,
    connector_id: UUID | None,
    application_idp_id: UUID | None,
    tag: str | None,
    metadata: dict[str, str] | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "project": str(project) if project else None,
        "member_type": str(member_type) if member_type else None,
        "connector_id": str(connector_id) if connector_id else None,
        "application_idp_id": (
            str(application_idp_id) if application_idp_id else None
        ),
        "tag": tag,
        "metadata": (
            [f"{key}:{value}" for key, value in metadata.items()]
            if metadata
            else None
        ),
        "limit": limit,
        "next": cursor,
    }


def _create_body(
    *,
    email: str,
    name: str,
    role: str | None,
    tags: builtins.list[str] | None,
    metadata: dict[str, str] | None,
) -> dict[str, Any]:
    return MemberCreateRequest(
        email=email, name=name, role=role, tags=tags, metadata=metadata
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    name: str | None,
    image_url: str | None,
    role: str | None,
    tags: builtins.list[str] | None,
    metadata: dict[str, str] | None,
) -> dict[str, Any]:
    # `exclude_none` drops an omitted field but keeps an explicit [] / {},
    # which is what clears tags / metadata — both replace wholesale.
    return MemberUpdateRequest(
        name=name,
        image_url=image_url,
        role=role,
        tags=tags,
        metadata=metadata,
    ).model_dump(mode="json", exclude_none=True)


class Members:
    """CP ``/v1/members`` namespace."""

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        project: str | UUID | None = None,
        member_type: MemberType | str | None = None,
        connector_id: UUID | None = None,
        application_idp_id: UUID | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Member, Paginated[Member]]:
        """List members. Iterate the returned :class:`Pager` to stream every
        member across pages, or call ``.page()`` for the first page only.

        Filters narrow and AND together. ``tag`` matches one access-bearing
        tag exactly. ``metadata`` matches members whose metadata holds every
        pair, each compared exactly against the string value; it is sent as
        one repeated ``metadata=key:value`` param per entry (distinct keys,
        at most 16). ``project`` is only needed by a credential that is not
        already org-scoped (a deployment token)."""

        def fetch(cursor: str | None) -> Paginated[Member]:
            params = _list_params(
                project=project,
                member_type=member_type,
                connector_id=connector_id,
                application_idp_id=application_idp_id,
                tag=tag,
                metadata=metadata,
                limit=limit,
                cursor=cursor,
            )
            payload = self._http.request("GET", "/v1/members", params=params)
            return Paginated[Member].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def get(
        self, member_id: UUID, *, project: str | UUID | None = None
    ) -> Member:
        payload = self._http.request(
            "GET",
            f"/v1/members/{member_id}",
            params={"project": str(project) if project else None},
        )
        return Member.model_validate(payload)

    def create(
        self,
        *,
        email: str,
        name: str,
        role: str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Member:
        """Invite a human member by email (admin or owner only).

        ``name`` must be a full name (first and last). ``tags`` are
        access-bearing, so passing any needs ``members:manage``.
        ``metadata`` keys are letters, digits, ``_`` and ``-``, values are
        non-empty strings, at most 64 entries per write; the server answers 422
        otherwise."""
        payload = self._http.request(
            "POST",
            "/v1/members",
            json=_create_body(
                email=email,
                name=name,
                role=role,
                tags=tags,
                metadata=metadata,
            ),
        )
        return Member.model_validate(payload)

    def update(
        self,
        member_id: UUID,
        *,
        name: str | None = None,
        image_url: str | None = None,
        role: str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Member:
        """Update a member (requires ``members:manage``).

        ``tags`` and ``metadata`` each replace wholesale: ``None`` leaves
        them untouched, ``[]`` / ``{}`` clears them. To change one metadata
        key, read the member, edit its map, and send the whole map back."""
        payload = self._http.request(
            "PATCH",
            f"/v1/members/{member_id}",
            json=_update_body(
                name=name,
                image_url=image_url,
                role=role,
                tags=tags,
                metadata=metadata,
            ),
        )
        return Member.model_validate(payload)


class AsyncMembers:
    """Async twin of :class:`Members` (CP ``/v1/members``)."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        project: str | UUID | None = None,
        member_type: MemberType | str | None = None,
        connector_id: UUID | None = None,
        application_idp_id: UUID | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Member, Paginated[Member]]:
        """List members. ``await`` the returned :class:`AsyncPager` for the
        first page, or ``async for`` it to stream every member across
        pages.

        Filters narrow and AND together. ``tag`` matches one access-bearing
        tag exactly. ``metadata`` matches members whose metadata holds every
        pair, each compared exactly against the string value; it is sent as
        one repeated ``metadata=key:value`` param per entry (distinct keys,
        at most 16). ``project`` is only needed by a credential that is not
        already org-scoped (a deployment token)."""

        async def fetch(cursor: str | None) -> Paginated[Member]:
            params = _list_params(
                project=project,
                member_type=member_type,
                connector_id=connector_id,
                application_idp_id=application_idp_id,
                tag=tag,
                metadata=metadata,
                limit=limit,
                cursor=cursor,
            )
            payload = await self._http.request(
                "GET", "/v1/members", params=params
            )
            return Paginated[Member].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(
        self, member_id: UUID, *, project: str | UUID | None = None
    ) -> Member:
        payload = await self._http.request(
            "GET",
            f"/v1/members/{member_id}",
            params={"project": str(project) if project else None},
        )
        return Member.model_validate(payload)

    async def create(
        self,
        *,
        email: str,
        name: str,
        role: str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Member:
        """Async twin of :meth:`Members.create`."""
        payload = await self._http.request(
            "POST",
            "/v1/members",
            json=_create_body(
                email=email,
                name=name,
                role=role,
                tags=tags,
                metadata=metadata,
            ),
        )
        return Member.model_validate(payload)

    async def update(
        self,
        member_id: UUID,
        *,
        name: str | None = None,
        image_url: str | None = None,
        role: str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Member:
        """Async twin of :meth:`Members.update`."""
        payload = await self._http.request(
            "PATCH",
            f"/v1/members/{member_id}",
            json=_update_body(
                name=name,
                image_url=image_url,
                role=role,
                tags=tags,
                metadata=metadata,
            ),
        )
        return Member.model_validate(payload)
