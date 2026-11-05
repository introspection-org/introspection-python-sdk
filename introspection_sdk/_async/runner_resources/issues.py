"""Re-exported by :mod:`introspection_sdk.runner_resources.issues`."""

from __future__ import annotations

import builtins
from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.issues import (
    Issue,
    IssueCreate,
    IssueEventReference,
    IssueFile,
    IssueLink,
    IssueMetadataValue,
    IssueMutation,
    IssueOwner,
    IssuePriority,
    IssueSpanReference,
    IssueStatus,
    IssueUpdate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.tasks import TaskStatus


def _path(issue_id: UUID | str) -> str:
    return f"/v1/issues/{quote(str(issue_id), safe='')}"


def _idempotency(key: str | None) -> dict[str, str] | None:
    return {"Idempotency-Key": key} if key is not None else None


def _values(values: builtins.list[Any] | None) -> builtins.list[str] | None:
    return [str(value) for value in values] if values else None


def _update_body(change: IssueUpdate | IssueMutation) -> dict[str, Any]:
    if isinstance(change, IssueUpdate):
        # `exclude_unset`: an omitted field stays omitted and is left as it
        # is, while an explicit `[]` or `{}` is sent and clears it.
        return change.model_dump(mode="json", exclude_unset=True)
    # `exclude_none`, not `exclude_unset`: the request id is minted by a
    # default factory and must still be sent.
    return change.model_dump(mode="json", exclude_none=True)


class AsyncIssues:
    """DP ``/v1/issues`` namespace."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        status: builtins.list[IssueStatus | str] | None = None,
        owner: builtins.list[IssueOwner | str] | None = None,
        assigned_to_me: bool | None = None,
        has_open_requests: bool | None = None,
        task_status: builtins.list[TaskStatus | str] | None = None,
        exclude_task_status: builtins.list[TaskStatus | str] | None = None,
        display_index: int | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
        search: str | None = None,
        include_total: bool = False,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Issue, Paginated[Issue]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List the issues the caller may read, newest activity first.
        ``await`` the returned :class:`AsyncPager` for the first page, or
        ``async for`` it to stream every issue across pages. See
        :meth:`Issues.list` for the filters."""
        # unasync: end
        """List the issues the caller may read, newest activity first.
        Iterate the returned :class:`Pager` to stream every issue across
        pages, or call ``.page()`` for the first page only.

        ``status``, ``owner`` and ``task_status`` each go out as one
        repeated param per value and OR together; the filters AND with each
        other. ``owner`` is ``project`` for project-owned issues and ``me``
        for the caller's own private ones. ``exclude_task_status`` keeps an
        issue without a live Task. ``tag`` is one ``key:value`` tag;
        ``metadata`` is sent as one ``metadata=key:value`` param per entry
        (at most 16). ``search`` is a case-insensitive substring of the
        title. ``limit`` is the page size (1-200, server default 50)."""

        async def fetch(cursor: str | None) -> Paginated[Issue]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "status": _values(status),
                "owner": _values(owner),
                "assigned_to_me": assigned_to_me,
                "has_open_requests": has_open_requests,
                "task_status": _values(task_status),
                "exclude_task_status": _values(exclude_task_status),
                "display_index": display_index,
                "tag": tag,
                "metadata": (
                    [f"{key}:{value}" for key, value in metadata.items()]
                    if metadata
                    else None
                ),
                "search": search,
                "include_total": include_total or None,
            }
            payload = await self._http.request(
                "GET", "/v1/issues", params=params
            )
            return Paginated[Issue].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, issue_id: UUID | str) -> Issue:
        """Read one issue with its evidence, open requests and current
        ``revision``."""
        return Issue.model_validate(
            await self._http.request("GET", _path(issue_id))
        )

    async def create(
        self,
        *,
        title: str,
        description: str,
        task_id: UUID | str,
        priority: IssuePriority | str | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue:
        """Open an issue on its fixed worker Task (``task_id``). It starts
        ``open``; change its status later with :meth:`update`.

        Resend the same ``idempotency_key`` when retrying one deliberate
        create so it applies once."""
        body = IssueCreate.model_validate(
            {
                "title": title,
                "description": description,
                "task_id": task_id,
                "priority": priority,
                "files": files,
                "links": links,
                "events": events,
                "spans": spans,
                "tags": tags,
                "metadata": metadata,
            }
        )
        payload = await self._http.request(
            "POST",
            "/v1/issues",
            json=body.model_dump(mode="json", exclude_none=True),
            headers=_idempotency(idempotency_key),
        )
        return Issue.model_validate(payload)

    async def update(
        self,
        issue_id: UUID | str,
        change: IssueUpdate | IssueMutation,
        *,
        idempotency_key: str | None = None,
    ) -> Issue:
        """Edit the brief (:class:`IssueUpdate`), or create or change one
        human request (:class:`IssueMutation`). Returns the updated issue.

        An :class:`IssueUpdate` sends only the fields set on it, so an
        omitted list is left as it is and ``[]`` clears it. A stale
        ``expected_revision`` answers 409
        (:class:`~introspection_sdk._errors.ConflictError`): read the issue
        again before retrying."""
        payload = await self._http.request(
            "PATCH",
            _path(issue_id),
            json=_update_body(change),
            headers=_idempotency(idempotency_key),
        )
        return Issue.model_validate(payload)

    async def delete(
        self,
        issue_id: UUID | str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        """Soft-delete an issue. Its activity history is kept."""
        await self._http.request(
            "DELETE",
            _path(issue_id),
            headers=_idempotency(idempotency_key),
            expect="empty",
        )
