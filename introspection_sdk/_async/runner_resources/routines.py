"""Re-exported by :mod:`introspection_sdk.runner_resources.routines`."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk._strict_schema import decode
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.routines import (
    Routine,
    RoutineCreateRequest,
    RoutineKind,
    RoutineMetadata,
    RoutineTriggerResponse,
    RoutineTriggerType,
    RoutineUpdateRequest,
)

MetadataInput = RoutineMetadata | dict[str, Any]


def _path(routine_id: UUID | str) -> str:
    return f"/v1/routines/{quote(str(routine_id), safe='')}"


def _list_params(
    *,
    kind: RoutineKind | str | None,
    enabled: bool | None,
    scheduled: bool | None,
    task_id: UUID | str | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "limit": limit,
        "next": cursor,
        "kind": str(kind) if kind else None,
        "enabled": enabled,
        "scheduled": scheduled,
        "task_id": str(task_id) if task_id else None,
    }


def _uuid(value: UUID | str | None) -> UUID | None:
    return value if value is None or isinstance(value, UUID) else UUID(value)


def _metadata(metadata: MetadataInput | None) -> dict[str, Any] | None:
    if isinstance(metadata, RoutineMetadata):
        return metadata.model_dump(mode="json", exclude_none=True)
    return metadata


def _create_body(
    *,
    name: str,
    trigger_type: RoutineTriggerType | str,
    description: str | None,
    cron_schedule: str | None,
    kind: RoutineKind | str | None,
    prompt: str | None,
    runtime_group_id: UUID | str | None,
    task_id: UUID | str | None,
    next_trigger_at: datetime | None,
    metadata: MetadataInput | None,
    enabled: bool | None,
) -> dict[str, Any]:
    return RoutineCreateRequest(
        name=name,
        trigger_type=trigger_type,
        description=description,
        cron_schedule=cron_schedule,
        kind=kind,
        prompt=prompt,
        runtime_group_id=_uuid(runtime_group_id),
        task_id=_uuid(task_id),
        next_trigger_at=next_trigger_at,
        metadata=_metadata(metadata),
        enabled=enabled,
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    name: str | None,
    description: str | None,
    cron_schedule: str | None,
    prompt: str | None,
    runtime_group_id: UUID | str | None,
    task_id: UUID | str | None,
    next_trigger_at: datetime | None,
    metadata: MetadataInput | None,
    enabled: bool | None,
) -> dict[str, Any]:
    # `exclude_none` is the whole PATCH contract: an unset field is absent,
    # and the server leaves an absent field as it is.
    return RoutineUpdateRequest(
        name=name,
        description=description,
        cron_schedule=cron_schedule,
        prompt=prompt,
        runtime_group_id=_uuid(runtime_group_id),
        task_id=_uuid(task_id),
        next_trigger_at=next_trigger_at,
        metadata=_metadata(metadata),
        enabled=enabled,
    ).model_dump(mode="json", exclude_none=True)


class AsyncRoutines:
    """DP ``/v1/routines`` namespace."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        kind: RoutineKind | str | None = None,
        enabled: bool | None = None,
        scheduled: bool | None = None,
        task_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Routine, Paginated[Routine]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List the project's routines. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every routine across pages. See :meth:`Routines.list`
        for the filters."""
        # unasync: end
        """List the project's routines. Iterate the returned
        :class:`Pager` to stream every routine across pages, or call
        ``.page()`` for the first page only.

        Filters AND together. ``scheduled=True`` keeps only routines with
        a next slot, ``False`` only those without. ``task_id`` keeps those
        that post into one task; the server accepts it only once
        introspection-cloud#3137 ships. ``limit`` is the page size (1-1000,
        server default 100)."""

        async def fetch(cursor: str | None) -> Paginated[Routine]:
            params = _list_params(
                kind=kind,
                enabled=enabled,
                scheduled=scheduled,
                task_id=task_id,
                limit=limit,
                cursor=cursor,
            )
            payload = await self._http.request(
                "GET", "/v1/routines", params=params
            )
            return decode(Paginated[Routine], payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, routine_id: UUID | str) -> Routine:
        """Read one routine, soft-deleted ones included."""
        return decode(
            Routine, await self._http.request("GET", _path(routine_id))
        )

    async def create(
        self,
        *,
        name: str,
        trigger_type: RoutineTriggerType | str,
        description: str | None = None,
        cron_schedule: str | None = None,
        kind: RoutineKind | str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Routine:
        """Create a routine.

        Omit ``kind`` for a prompt routine, which then needs ``prompt``
        and a ``runtime_group_id``. ``task_id`` posts each firing into that
        existing task instead of creating one. A one-off reminder is
        ``trigger_type="manual"`` with a future, timezone-aware
        ``next_trigger_at``; a ``cron`` routine needs ``cron_schedule``
        (or ``metadata.cron_schedules``) and must not send a slot.
        ``metadata`` takes an :class:`RoutineMetadata` or a plain dict.
        """
        payload = await self._http.request(
            "POST",
            "/v1/routines",
            json=_create_body(
                name=name,
                trigger_type=trigger_type,
                description=description,
                cron_schedule=cron_schedule,
                kind=kind,
                prompt=prompt,
                runtime_group_id=runtime_group_id,
                task_id=task_id,
                next_trigger_at=next_trigger_at,
                metadata=metadata,
                enabled=enabled,
            ),
        )
        return decode(Routine, payload)

    async def update(
        self,
        routine_id: UUID | str,
        *,
        name: str | None = None,
        description: str | None = None,
        cron_schedule: str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Routine:
        """Update a routine. Only the fields you pass are sent; ``None``
        leaves a field as it is, so nothing can be cleared. ``kind`` and
        ``trigger_type`` are immutable and ``metadata`` replaces wholesale.
        ``enabled=False`` pauses and keeps the slot."""
        payload = await self._http.request(
            "PATCH",
            _path(routine_id),
            json=_update_body(
                name=name,
                description=description,
                cron_schedule=cron_schedule,
                prompt=prompt,
                runtime_group_id=runtime_group_id,
                task_id=task_id,
                next_trigger_at=next_trigger_at,
                metadata=metadata,
                enabled=enabled,
            ),
        )
        return decode(Routine, payload)

    async def delete(self, routine_id: UUID | str) -> None:
        """Soft-delete a routine. A project default
        (``observation_synthesis``, ``project_check_in``) cannot be deleted
        and answers 409; disable it instead."""
        await self._http.request("DELETE", _path(routine_id), expect="empty")

    async def trigger(self, routine_id: UUID | str) -> RoutineTriggerResponse:
        """Run a routine now (``POST /v1/routines/{id}/trigger``).

        Returns the task it created or posted into. A ``skipped`` status
        carries its ``reason``. Neither reads nor clears a scheduled slot.
        """
        payload = await self._http.request(
            "POST", f"{_path(routine_id)}/trigger"
        )
        return decode(RoutineTriggerResponse, payload)
