"""Re-exported by :mod:`introspection_sdk.runner_resources.aauth`."""

from __future__ import annotations

import builtins
from typing import Any
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.aauth import (
    Approval,
    ApprovalKind,
    ApprovalStatus,
    Mission,
)
from introspection_sdk.schemas.pagination import Paginated


class AsyncMissions:
    """DP ``/v1/aauth/missions``: the missions the project's people approved
    agents to carry out."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        member_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Mission, Paginated[Mission]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List missions, newest first; ``member_id`` keeps one person's.
        ``await`` the returned :class:`AsyncPager` for the first page, or
        ``async for`` it to stream every mission."""
        # unasync: end
        """List missions, newest first; ``member_id`` keeps one person's.
        Iterate the returned :class:`Pager` to stream every mission, or
        call ``.page()`` for the first page."""

        async def fetch(cursor: str | None) -> Paginated[Mission]:
            payload = await self._http.request(
                "GET",
                "/v1/aauth/missions",
                params={
                    "member_id": str(member_id) if member_id else None,
                    "limit": limit,
                    "next": cursor,
                },
            )
            return Paginated[Mission].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)


class AsyncApprovals:
    """DP ``/v1/aauth/approvals``: the decisions agents ask the project's
    people to make."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        status: builtins.list[ApprovalStatus | str] | None = None,
        kind: ApprovalKind | str | None = None,
        member_id: UUID | str | None = None,
        decided_by_member_id: UUID | str | None = None,
        mission_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Approval, Paginated[Approval]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List approvals, filtered by ``status`` (any of), ``kind``, the
        person asked, who decided, and the mission. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every approval."""
        # unasync: end
        """List approvals, filtered by ``status`` (any of), ``kind``, the
        person asked, who decided, and the mission. Iterate the returned
        :class:`Pager` to stream every approval, or call ``.page()`` for
        the first page."""

        def _id(value: UUID | str | None) -> str | None:
            return str(value) if value else None

        async def fetch(cursor: str | None) -> Paginated[Approval]:
            params: dict[str, Any] = {
                "status": [str(s) for s in status] if status else None,
                "kind": str(kind) if kind is not None else None,
                "member_id": _id(member_id),
                "decided_by_member_id": _id(decided_by_member_id),
                "mission_id": _id(mission_id),
                "limit": limit,
                "next": cursor,
            }
            payload = await self._http.request(
                "GET", "/v1/aauth/approvals", params=params
            )
            return Paginated[Approval].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)


class AsyncAAuth:
    """DP ``/v1/aauth`` namespace: :attr:`missions` and :attr:`approvals`."""

    missions: AsyncMissions
    approvals: AsyncApprovals

    def __init__(self, http: _AsyncHttpClient) -> None:
        self.missions = AsyncMissions(http)
        self.approvals = AsyncApprovals(http)
