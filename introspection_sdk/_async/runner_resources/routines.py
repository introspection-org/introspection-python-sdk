"""Re-exported by :mod:`introspection_sdk.runner_resources.routines`."""

from __future__ import annotations

import builtins
import errno
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from pydantic import TypeAdapter

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
    RoutineUpdateRequest,
)
from introspection_sdk.schemas.tasks import TaskFileRef

TriggerInput = RoutineTriggerSpec | dict[str, Any]
MetadataInput = RoutineMetadata | dict[str, Any]
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


_TRIGGER_SPECS: TypeAdapter[list[RoutineTriggerSpec]] = TypeAdapter(
    list[RoutineTriggerSpec]
)


def _triggers(
    triggers: list[TriggerInput] | None,
) -> list[RoutineTriggerSpec] | None:
    if triggers is None:
        return None
    return _TRIGGER_SPECS.validate_python(triggers)


def _metadata(metadata: MetadataInput | None) -> RoutineMetadata | None:
    if metadata is None:
        return None
    return RoutineMetadata.model_validate(metadata)


def _create_body(
    *,
    name: str,
    description: str | None,
    kind: RoutineKind | str | None,
    prompt: str | None,
    runtime_group_id: UUID | str | None,
    task_id: UUID | str | None,
    next_trigger_at: datetime | None,
    enabled: bool | None,
    routine_metadata: MetadataInput | None,
    triggers: list[TriggerInput] | None,
) -> dict[str, Any]:
    return RoutineCreateRequest(
        name=name,
        description=description,
        kind=kind,
        prompt=prompt,
        runtime_group_id=_uuid(runtime_group_id),
        task_id=_uuid(task_id),
        next_trigger_at=next_trigger_at,
        enabled=enabled,
        routine_metadata=_metadata(routine_metadata),
        triggers=_triggers(triggers),
    ).model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    name: str | None,
    description: str | None,
    prompt: str | None,
    runtime_group_id: UUID | str | None,
    task_id: UUID | str | None,
    next_trigger_at: datetime | None,
    enabled: bool | None,
    routine_metadata: MetadataInput | None,
    triggers: list[TriggerInput] | None,
) -> dict[str, Any]:
    # `exclude_none` is the whole PATCH contract: an unset field is absent,
    # and the server leaves an absent field as it is.
    return RoutineUpdateRequest(
        name=name,
        description=description,
        prompt=prompt,
        runtime_group_id=_uuid(runtime_group_id),
        task_id=_uuid(task_id),
        next_trigger_at=next_trigger_at,
        enabled=enabled,
        routine_metadata=_metadata(routine_metadata),
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


def _parameters_ref(file: File | UUID) -> TaskFileRef:
    file_id = file.id if isinstance(file, File) else file
    return TaskFileRef(id=str(file_id), name=PARAMETERS_FILE_NAME)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _read_parameters(source: str | os.PathLike[Any]) -> dict[str, Any]:
    path = Path(os.fspath(source))
    if not path.is_file():
        if isinstance(source, str) and _is_uuid(source):
            raise ValueError(
                f"parameters={source!r} names no local file; to reference a "
                "Files API file pass UUID(...) or the File"
            )
        raise FileNotFoundError(
            errno.ENOENT, "No such parameters file", str(path)
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return value


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
        description: str | None = None,
        kind: RoutineKind | str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        next_trigger_at: datetime | None = None,
        enabled: bool | None = None,
        routine_metadata: MetadataInput | None = None,
        triggers: builtins.list[TriggerInput] | None = None,
    ) -> Routine:
        """Create a routine.

        Omit ``kind`` for a prompt routine, which then needs ``prompt``
        and a ``runtime_group_id``. ``task_id`` posts each firing into that
        existing task instead of creating one.

        ``triggers`` (at most 20) are what start a run besides
        :meth:`trigger`, each a :data:`RoutineTriggerSpec` variant or a
        plain dict discriminated on ``type``: ``schedule`` (``cron``,
        ``timezone``), ``slack``, ``github``, ``linear`` or ``webhook``.
        A routine with no ``schedule`` trigger may set a future,
        timezone-aware ``next_trigger_at`` to run once (a one-off
        reminder). Event triggers are an administrator's, on a prompt
        routine that starts a task per run.
        """
        payload = await self._http.request(
            "POST",
            "/v1/routines",
            json=_create_body(
                name=name,
                description=description,
                kind=kind,
                prompt=prompt,
                runtime_group_id=runtime_group_id,
                task_id=task_id,
                next_trigger_at=next_trigger_at,
                enabled=enabled,
                routine_metadata=routine_metadata,
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
        prompt: str | None = None,
        runtime_group_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        next_trigger_at: datetime | None = None,
        enabled: bool | None = None,
        routine_metadata: MetadataInput | None = None,
        triggers: builtins.list[TriggerInput] | None = None,
    ) -> Routine:
        """Update a routine. Only the fields you pass are sent; ``None``
        leaves a field as it is, so nothing can be cleared. ``kind`` is
        immutable. ``enabled=False`` pauses and keeps the slot.
        ``routine_metadata`` replaces the whole object, so send the values
        you keep.

        ``triggers`` replaces the routine's triggers, schedules and events
        alike: an entry with the ``id`` of an existing trigger keeps it
        (its ``type`` is fixed), one without is new, and every trigger not
        listed is removed, so ``[]`` removes them all. A routine's own
        ``triggers`` can be passed back as they are."""
        payload = await self._http.request(
            "PATCH",
            _path(routine_id),
            json=_update_body(
                name=name,
                description=description,
                prompt=prompt,
                runtime_group_id=runtime_group_id,
                task_id=task_id,
                next_trigger_at=next_trigger_at,
                enabled=enabled,
                routine_metadata=routine_metadata,
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
        parameters: dict[str, Any]
        | str
        | os.PathLike[str]
        | UUID
        | File
        | None = None,
        files: builtins.list[FileRefInput] | None = None,
        attach_parameters_file: bool | None = None,
    ) -> RoutineTriggerResponse:
        """Run a routine now (``POST /v1/routines/{id}/trigger``).

        ``parameters`` is the run's parameters, in one of three forms:

        - A ``dict``: the JSON object itself (at most 16 KiB serialized and
          8 levels deep, else 422), sent inline. Each ``@parameters.<name>``
          in a prompt routine's prompt is replaced by that value as JSON
          (``null`` when absent). For a routine that starts its own task,
          the SDK first uploads it through the Files API under a unique
          ``routine-parameters/<uuid>.json`` (expiring after 30 days) and
          attaches that file as the run's ``parameters.json``. A platform
          routine (one with a ``kind``) or one that posts into an existing
          task takes no files, so it is sent the object alone:
          ``observation_synthesis`` takes ``{"conversation_ids": [...]}``
          (1-100). ``attach_parameters_file`` decides this; left ``None``,
          the SDK reads the routine first, and ``True`` / ``False`` skip
          that read.
        - A ``str`` or path: a local JSON file holding an object, read and
          then sent exactly as the ``dict`` form. A missing file raises
          :class:`FileNotFoundError`; a string that names no file but is a
          UUID raises :class:`ValueError`, since a Files API file is
          referenced by ``UUID(...)`` or its ``File``.
        - A :class:`~uuid.UUID` or
          :class:`~introspection_sdk.schemas.files.File`: an already-uploaded
          Files API file holding a JSON object (at most 256 KiB), attached
          as ``parameters.json``; the server reads the parameters from it.
          Nothing is read locally or uploaded, and the routine is not read.

        ``files`` are further Files API references
        (:class:`~introspection_sdk.schemas.tasks.TaskFileRef` or dicts)
        attached to the run's task, at most 100 in all.

        Returns the task it created or posted into, and the kind's
        ``result`` (``observation_synthesis``: ``enqueued`` and
        ``conversations``). A ``skipped`` status carries its ``reason``.
        Neither reads nor clears a scheduled slot.
        """
        refs = [TaskFileRef.model_validate(ref) for ref in files or []]
        inline: dict[str, Any] | None = None
        if isinstance(parameters, File | UUID):
            refs.insert(0, _parameters_ref(parameters))
        elif parameters is not None:
            inline = (
                _read_parameters(parameters)
                if isinstance(parameters, str | os.PathLike)
                else parameters
            )
            if attach_parameters_file is None:
                attach_parameters_file = _starts_own_task(
                    await self.get(routine_id)
                )
            if attach_parameters_file:
                uploaded = await self._files.create_text(
                    name=f"routine-parameters/{uuid4()}.json",
                    content=json.dumps(inline),
                    mime_type="application/json",
                    ttl_seconds=PARAMETERS_FILE_TTL_SECONDS,
                )
                refs.insert(0, _parameters_ref(uploaded))
        # Nothing to send sends no body, which the server reads as none.
        payload = await self._http.request(
            "POST",
            f"{_path(routine_id)}/trigger",
            json=_trigger_body(inline, refs),
        )
        return decode(RoutineTriggerResponse, payload)
