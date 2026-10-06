"""``client.issues`` / ``runner.issues`` — DP namespace for ``/v1/issues``.

An issue is a project pursuit: a living brief (title, description,
evidence) worked by one fixed worker task. Its history is the OTel activity
stream, readable through ``events``.

Writes run as durable commands on the data plane. ``update`` is
optimistic: it edits the brief at ``expected_revision`` and answers 409
when the issue has moved on. ``create``, ``update`` and ``delete`` take an
``idempotency_key`` so a retried call is applied once.
"""

from __future__ import annotations

import builtins
from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.issues import (
    Issue,
    IssueCreateRequest,
    IssueEventReference,
    IssueFile,
    IssueLink,
    IssueMetadataValue,
    IssueOwner,
    IssuePriority,
    IssueSpanReference,
    IssueStatus,
    IssueUpdateRequest,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.tasks import TaskStatus

ISSUES_PATH = "/v1/issues"


def _path(issue_id: UUID | str) -> str:
    return f"{ISSUES_PATH}/{quote(str(issue_id), safe='')}"


def _strings(values: builtins.list[Any] | None) -> builtins.list[str] | None:
    return [str(v) for v in values] if values else None


def _list_params(
    *,
    status: builtins.list[IssueStatus | str] | None,
    owner: builtins.list[IssueOwner | str] | None,
    assigned_to_me: bool | None,
    has_open_requests: bool | None,
    task_status: builtins.list[TaskStatus | str] | None,
    exclude_task_status: builtins.list[TaskStatus | str] | None,
    display_index: int | None,
    tag: str | None,
    metadata: dict[str, str] | None,
    search: str | None,
    include_total: bool,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "next": cursor,
        "status": _strings(status),
        "owner": _strings(owner),
        "assigned_to_me": assigned_to_me,
        "has_open_requests": has_open_requests,
        "task_status": _strings(task_status),
        "exclude_task_status": _strings(exclude_task_status),
        "display_index": display_index,
        "tag": tag,
        "metadata": (
            [f"{key}:{value}" for key, value in metadata.items()]
            if metadata
            else None
        ),
        "search": search,
        "include_total": True if include_total else None,
    }


def _headers(idempotency_key: str | None) -> dict[str, str] | None:
    return {"Idempotency-Key": idempotency_key} if idempotency_key else None


def _create_body(
    *,
    title: str,
    description: str,
    task_id: UUID | str,
    priority: IssuePriority | str | None,
    tags: builtins.list[str] | None,
    metadata: dict[str, IssueMetadataValue] | None,
    files: builtins.list[IssueFile] | None,
    links: builtins.list[IssueLink] | None,
    events: builtins.list[IssueEventReference] | None,
    spans: builtins.list[IssueSpanReference] | None,
) -> dict[str, Any]:
    return IssueCreateRequest(
        title=title,
        description=description,
        task_id=UUID(str(task_id)),
        priority=priority,
        tags=tags,
        metadata=metadata,
        files=files,
        links=links,
        events=events,
        spans=spans,
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    expected_revision: int,
    title: str | None,
    description: str | None,
    priority: IssuePriority | str | None,
    status: IssueStatus | str | None,
    tags: builtins.list[str] | None,
    metadata: dict[str, IssueMetadataValue] | None,
    files: builtins.list[IssueFile] | None,
    links: builtins.list[IssueLink] | None,
    events: builtins.list[IssueEventReference] | None,
    spans: builtins.list[IssueSpanReference] | None,
) -> dict[str, Any]:
    # `exclude_none` is the PATCH contract: an unset field is absent and left
    # as it is. `[]` / `{}` still go out, and clear tags or metadata.
    return IssueUpdateRequest(
        expected_revision=expected_revision,
        title=title,
        description=description,
        priority=priority,
        status=status,
        tags=tags,
        metadata=metadata,
        files=files,
        links=links,
        events=events,
        spans=spans,
    ).model_dump(mode="json", exclude_none=True)


class Issues:
    """DP ``/v1/issues`` namespace."""

    def __init__(self, http: _HttpClient) -> None:
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
    ) -> Pager[Issue, Paginated[Issue]]:
        """List issues, newest activity first. Iterate the returned
        :class:`Pager` to stream every issue across pages, or call
        ``.page()`` for the first page only.

        ``status``, ``owner``, ``task_status`` and ``exclude_task_status``
        are ORed within themselves; every filter ANDs with the others.
        ``owner=["me"]`` keeps the caller's own private issues,
        ``["project"]`` the project-owned ones. ``metadata`` narrows to
        issues holding every pair (at most 16). ``search`` is a
        case-insensitive substring of the title. ``limit`` is the page size
        (1-200, server default 50)."""

        def fetch(cursor: str | None) -> Paginated[Issue]:
            params = _list_params(
                status=status,
                owner=owner,
                assigned_to_me=assigned_to_me,
                has_open_requests=has_open_requests,
                task_status=task_status,
                exclude_task_status=exclude_task_status,
                display_index=display_index,
                tag=tag,
                metadata=metadata,
                search=search,
                include_total=include_total,
                limit=limit,
                cursor=cursor,
            )
            payload = self._http.request("GET", ISSUES_PATH, params=params)
            return Paginated[Issue].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def create(
        self,
        *,
        title: str,
        description: str,
        task_id: UUID | str,
        priority: IssuePriority | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue:
        """Open an issue worked by the existing task ``task_id``."""
        payload = self._http.request(
            "POST",
            ISSUES_PATH,
            json=_create_body(
                title=title,
                description=description,
                task_id=task_id,
                priority=priority,
                tags=tags,
                metadata=metadata,
                files=files,
                links=links,
                events=events,
                spans=spans,
            ),
            headers=_headers(idempotency_key),
        )
        return Issue.model_validate(payload)

    def get(self, issue_id: UUID | str) -> Issue:
        """Read one issue."""
        return Issue.model_validate(self._http.request("GET", _path(issue_id)))

    def update(
        self,
        issue_id: UUID | str,
        *,
        expected_revision: int,
        title: str | None = None,
        description: str | None = None,
        priority: IssuePriority | str | None = None,
        status: IssueStatus | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue:
        """Edit the brief at ``expected_revision`` (the issue's current
        ``revision``); a stale revision answers 409. Only the fields you
        pass are sent. ``tags`` and ``metadata`` replace wholesale, so
        ``[]`` / ``{}`` clear them."""
        payload = self._http.request(
            "PATCH",
            _path(issue_id),
            json=_update_body(
                expected_revision=expected_revision,
                title=title,
                description=description,
                priority=priority,
                status=status,
                tags=tags,
                metadata=metadata,
                files=files,
                links=links,
                events=events,
                spans=spans,
            ),
            headers=_headers(idempotency_key),
        )
        return Issue.model_validate(payload)

    def delete(
        self, issue_id: UUID | str, *, idempotency_key: str | None = None
    ) -> None:
        """Soft-delete an issue."""
        self._http.request(
            "DELETE",
            _path(issue_id),
            headers=_headers(idempotency_key),
            expect="empty",
        )


class AsyncIssues:
    """Async twin of :class:`Issues` (DP ``/v1/issues``)."""

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
        """Async twin of :meth:`Issues.list`."""

        async def fetch(cursor: str | None) -> Paginated[Issue]:
            params = _list_params(
                status=status,
                owner=owner,
                assigned_to_me=assigned_to_me,
                has_open_requests=has_open_requests,
                task_status=task_status,
                exclude_task_status=exclude_task_status,
                display_index=display_index,
                tag=tag,
                metadata=metadata,
                search=search,
                include_total=include_total,
                limit=limit,
                cursor=cursor,
            )
            payload = await self._http.request(
                "GET", ISSUES_PATH, params=params
            )
            return Paginated[Issue].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def create(
        self,
        *,
        title: str,
        description: str,
        task_id: UUID | str,
        priority: IssuePriority | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue:
        """Async twin of :meth:`Issues.create`."""
        payload = await self._http.request(
            "POST",
            ISSUES_PATH,
            json=_create_body(
                title=title,
                description=description,
                task_id=task_id,
                priority=priority,
                tags=tags,
                metadata=metadata,
                files=files,
                links=links,
                events=events,
                spans=spans,
            ),
            headers=_headers(idempotency_key),
        )
        return Issue.model_validate(payload)

    async def get(self, issue_id: UUID | str) -> Issue:
        """Async twin of :meth:`Issues.get`."""
        return Issue.model_validate(
            await self._http.request("GET", _path(issue_id))
        )

    async def update(
        self,
        issue_id: UUID | str,
        *,
        expected_revision: int,
        title: str | None = None,
        description: str | None = None,
        priority: IssuePriority | str | None = None,
        status: IssueStatus | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue:
        """Async twin of :meth:`Issues.update`."""
        payload = await self._http.request(
            "PATCH",
            _path(issue_id),
            json=_update_body(
                expected_revision=expected_revision,
                title=title,
                description=description,
                priority=priority,
                status=status,
                tags=tags,
                metadata=metadata,
                files=files,
                links=links,
                events=events,
                spans=spans,
            ),
            headers=_headers(idempotency_key),
        )
        return Issue.model_validate(payload)

    async def delete(
        self, issue_id: UUID | str, *, idempotency_key: str | None = None
    ) -> None:
        """Async twin of :meth:`Issues.delete`."""
        await self._http.request(
            "DELETE",
            _path(issue_id),
            headers=_headers(idempotency_key),
            expect="empty",
        )
