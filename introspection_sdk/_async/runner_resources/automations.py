"""Async twins re-exported by :mod:`introspection_sdk.runner_resources.automations`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.runner_resources._automations_common import (
    MetadataInput,
    _create_body,
    _list_params,
    _path,
    _update_body,
)
from introspection_sdk.schemas.automations import (
    Automation,
    AutomationKind,
    AutomationTriggerResponse,
    AutomationTriggerType,
)
from introspection_sdk.schemas.pagination import Paginated


class AsyncAutomations:
    """DP ``/v1/automations`` namespace."""

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        *,
        kind: AutomationKind | str | None = None,
        enabled: bool | None = None,
        scheduled: bool | None = None,
        task_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Automation, Paginated[Automation]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List the project's automations. ``await`` the returned
        :class:`AsyncPager` for the first page, or ``async for`` it to
        stream every automation across pages. See :meth:`Automations.list`
        for the filters."""
        # unasync: end
        """List the project's automations. Iterate the returned
        :class:`Pager` to stream every automation across pages, or call
        ``.page()`` for the first page only.

        Filters AND together. ``scheduled=True`` keeps only automations with
        a next slot, ``False`` only those without. ``task_id`` keeps those
        that post into one task; the server accepts it only once
        introspection-cloud#3137 ships. ``limit`` is the page size (1-1000,
        server default 100)."""

        async def fetch(cursor: str | None) -> Paginated[Automation]:
            params = _list_params(
                kind=kind,
                enabled=enabled,
                scheduled=scheduled,
                task_id=task_id,
                limit=limit,
                cursor=cursor,
            )
            payload = await self._http.request(
                "GET", "/v1/automations", params=params
            )
            return Paginated[Automation].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def get(self, automation_id: UUID | str) -> Automation:
        """Read one automation, soft-deleted ones included."""
        return Automation.model_validate(
            await self._http.request("GET", _path(automation_id))
        )

    async def create(
        self,
        *,
        name: str,
        trigger_type: AutomationTriggerType | str,
        description: str | None = None,
        cron_schedule: str | None = None,
        kind: AutomationKind | str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Automation:
        """Create an automation.

        Omit ``kind`` for a prompt automation, which then needs ``prompt``
        and a ``runtime_group_id``. ``task_id`` posts each firing into that
        existing task instead of creating one. A one-off reminder is
        ``trigger_type="manual"`` with a future, timezone-aware
        ``next_trigger_at``; a ``cron`` automation needs ``cron_schedule``
        (or ``metadata.cron_schedules``) and must not send a slot.
        ``metadata`` takes an :class:`AutomationMetadata` or a plain dict.
        """
        payload = await self._http.request(
            "POST",
            "/v1/automations",
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
        return Automation.model_validate(payload)

    async def update(
        self,
        automation_id: UUID | str,
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
    ) -> Automation:
        """Update an automation. Only the fields you pass are sent; ``None``
        leaves a field as it is, so nothing can be cleared. ``kind`` and
        ``trigger_type`` are immutable and ``metadata`` replaces wholesale.
        ``enabled=False`` pauses and keeps the slot."""
        payload = await self._http.request(
            "PATCH",
            _path(automation_id),
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
        return Automation.model_validate(payload)

    async def delete(self, automation_id: UUID | str) -> None:
        """Soft-delete an automation. A project default
        (``observation_synthesis``, ``project_check_in``) cannot be deleted
        and answers 409; disable it instead."""
        await self._http.request(
            "DELETE", _path(automation_id), expect="empty"
        )

    async def trigger(
        self, automation_id: UUID | str
    ) -> AutomationTriggerResponse:
        """Run an automation now (``POST /v1/automations/{id}/trigger``).

        Returns the task it created or posted into. A ``skipped`` status
        carries its ``reason``. Neither reads nor clears a scheduled slot.
        """
        payload = await self._http.request(
            "POST", f"{_path(automation_id)}/trigger"
        )
        return AutomationTriggerResponse.model_validate(payload)
