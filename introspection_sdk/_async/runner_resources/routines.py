"""Re-exported by :mod:`introspection_sdk.runner_resources.routines`."""

from __future__ import annotations

import builtins
import json
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from introspection_sdk._async.runner_resources.files import AsyncFiles
from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk._strict_schema import decode
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.schemas.files import File
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.routines import (
    Routine,
    RoutineCreateRequest,
    RoutineKind,
    RoutineMetadata,
    RoutineTriggerRequest,
    RoutineTriggerResponse,
    RoutineTriggerSpec,
    RoutineTriggerType,
    RoutineUpdateRequest,
)
from introspection_sdk.schemas.tasks import TaskFileRef

MetadataInput = RoutineMetadata | dict[str, Any]
TriggerInput = RoutineTriggerSpec | dict[str, Any]
FileRefInput = TaskFileRef | dict[str, Any]

PARAMETERS_FILE_NAME = "parameters.json"
"""The name a run's parameters file takes among its task's files."""
PARAMETERS_FILE_TTL_SECONDS = 30 * 24 * 60 * 60
"""How long an uploaded parameters file lives: the Files API's maximum."""


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


def _triggers(
    triggers: list[TriggerInput] | None,
) -> list[RoutineTriggerSpec] | None:
    if triggers is None:
        return None
    return [RoutineTriggerSpec.model_validate(trigger) for trigger in triggers]


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
    triggers: list[TriggerInput] | None,
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
        triggers=_triggers(triggers),
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    name: str | None,
    description: str | None,
    trigger_type: RoutineTriggerType | str | None,
    cron_schedule: str | None,
    prompt: str | None,
    runtime_group_id: UUID | str | None,
    task_id: UUID | str | None,
    next_trigger_at: datetime | None,
    metadata: MetadataInput | None,
    enabled: bool | None,
    triggers: list[TriggerInput] | None,
) -> dict[str, Any]:
    # `exclude_none` is the whole PATCH contract: an unset field is absent,
    # and the server leaves an absent field as it is.
    return RoutineUpdateRequest(
        name=name,
        description=description,
        trigger_type=trigger_type,
        cron_schedule=cron_schedule,
        prompt=prompt,
        runtime_group_id=_uuid(runtime_group_id),
        task_id=_uuid(task_id),
        next_trigger_at=next_trigger_at,
        metadata=_metadata(metadata),
        enabled=enabled,
        triggers=_triggers(triggers),
    ).model_dump(mode="json", exclude_none=True)


def _trigger_body(
    parameters: dict[str, Any] | None,
    files: list[TaskFileRef],
) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}
    if parameters is not None:
        fields["parameters"] = parameters
    if files:
        fields["files"] = files
    if not fields:
        return None
    # `exclude_unset`, not `exclude_none`: a null inside parameters is data.
    return RoutineTriggerRequest(**fields).model_dump(
        mode="json", exclude_unset=True
    )


def _parameters_ref(file: File | str) -> TaskFileRef:
    file_id = file.id if isinstance(file, File) else file
    return TaskFileRef(id=str(file_id), name=PARAMETERS_FILE_NAME)


def _starts_own_task(routine: Routine) -> bool:
    return routine.kind is None and routine.task_id is None


class AsyncRoutines:
    """DP ``/v1/routines`` namespace."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self._files = AsyncFiles(http)

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
        triggers: builtins.list[TriggerInput] | None = None,
    ) -> Routine:
        """Create a routine.

        Omit ``kind`` for a prompt routine, which then needs ``prompt``
        and a ``runtime_group_id``. ``task_id`` posts each firing into that
        existing task instead of creating one. A one-off reminder is
        ``trigger_type="manual"`` with a future, timezone-aware
        ``next_trigger_at``; a ``cron`` routine needs ``cron_schedule``
        (or ``metadata.cron_schedules``) and must not send a slot.
        ``metadata`` takes an :class:`RoutineMetadata` or a plain dict.

        ``triggers`` are events that start a run (at most 20), each a
        :class:`RoutineTriggerSpec` or a plain dict, for a prompt routine
        that starts a task per run. An event-started run receives the
        event's body as ``parameters.json`` and ``@parameters.<key>`` in
        the prompt reads its top-level keys, as a manual run's
        ``parameters`` do. Only an administrator can add triggers.
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
                triggers=triggers,
            ),
        )
        return decode(Routine, payload)

    async def update(
        self,
        routine_id: UUID | str,
        *,
        name: str | None = None,
        description: str | None = None,
        trigger_type: RoutineTriggerType | str | None = None,
        cron_schedule: str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
        triggers: builtins.list[TriggerInput] | None = None,
    ) -> Routine:
        """Update a routine. Only the fields you pass are sent; ``None``
        leaves a field as it is, so nothing can be cleared. ``kind`` is
        immutable and ``metadata`` replaces wholesale. ``enabled=False``
        pauses and keeps the slot.

        ``trigger_type`` switches a prompt routine between ``manual`` and
        ``cron``: ``cron`` needs a ``cron_schedule`` (or
        ``metadata.cron_schedules``) in the same update, and ``manual``
        drops the next slot. A schedule list may not repeat a cron (422).

        ``triggers`` replaces the routine's event triggers: an entry with
        the ``id`` of an existing trigger keeps it (with the fields given),
        one without is new, and every trigger not listed is removed, so
        ``[]`` removes them all."""
        payload = await self._http.request(
            "PATCH",
            _path(routine_id),
            json=_update_body(
                name=name,
                description=description,
                trigger_type=trigger_type,
                cron_schedule=cron_schedule,
                prompt=prompt,
                runtime_group_id=runtime_group_id,
                task_id=task_id,
                next_trigger_at=next_trigger_at,
                metadata=metadata,
                enabled=enabled,
                triggers=triggers,
            ),
        )
        return decode(Routine, payload)

    async def delete(self, routine_id: UUID | str) -> None:
        """Soft-delete a routine. A project default
        (``observation_synthesis``, ``project_check_in``) cannot be deleted
        and answers 409; disable it instead."""
        await self._http.request("DELETE", _path(routine_id), expect="empty")

    async def trigger(
        self,
        routine_id: UUID | str,
        *,
        parameters: dict[str, Any] | None = None,
        parameters_file: File | str | None = None,
        files: builtins.list[FileRefInput] | None = None,
        attach_parameters_file: bool | None = None,
    ) -> RoutineTriggerResponse:
        """Run a routine now (``POST /v1/routines/{id}/trigger``).

        ``parameters`` is the run's JSON object (at most 16 KiB serialized
        and 8 levels deep, else 422). Each ``@parameters.<name>`` in a
        prompt routine's prompt is replaced by that value as JSON (``null``
        when absent). For a routine that starts its own task, the SDK first
        uploads them through the Files API under a unique
        ``routine-parameters/<uuid>.json`` (expiring after 30 days) and
        attaches that file as the run's ``parameters.json``. A platform
        routine (one with a ``kind``) or one that posts into an existing
        task takes no files, so it is sent ``parameters`` alone:
        ``observation_synthesis`` takes ``{"conversation_ids": [...]}``
        (1-100). ``attach_parameters_file`` decides this; left ``None``,
        the SDK reads the routine first, and ``True`` / ``False`` skip
        that read.

        ``parameters_file`` is an already-uploaded JSON object file (a
        :class:`~introspection_sdk.schemas.files.File` or its id), attached
        as ``parameters.json``; the server reads the parameters from it (at
        most 256 KiB). Not with ``parameters``.

        ``files`` are further Files API references
        (:class:`~introspection_sdk.schemas.tasks.TaskFileRef` or dicts)
        attached to the run's task, at most 100 in all.

        Returns the task it created or posted into, and the kind's
        ``result`` (``observation_synthesis``: ``enqueued`` and
        ``conversations``). A ``skipped`` status carries its ``reason``.
        Neither reads nor clears a scheduled slot.
        """
        if parameters is not None and parameters_file is not None:
            raise ValueError("pass parameters or parameters_file, not both")
        refs = [TaskFileRef.model_validate(ref) for ref in files or []]
        if parameters_file is not None:
            refs.insert(0, _parameters_ref(parameters_file))
        elif parameters is not None:
            if attach_parameters_file is None:
                attach_parameters_file = _starts_own_task(
                    await self.get(routine_id)
                )
            if attach_parameters_file:
                uploaded = await self._files.create_text(
                    name=f"routine-parameters/{uuid4()}.json",
                    content=json.dumps(parameters),
                    mime_type="application/json",
                    ttl_seconds=PARAMETERS_FILE_TTL_SECONDS,
                )
                refs.insert(0, _parameters_ref(uploaded))
        # Nothing to send sends no body, which the server reads as none.
        payload = await self._http.request(
            "POST",
            f"{_path(routine_id)}/trigger",
            json=_trigger_body(parameters, refs),
        )
        return decode(RoutineTriggerResponse, payload)
