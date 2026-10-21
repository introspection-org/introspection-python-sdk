"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.automations`."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from introspection_sdk.schemas.automations import (
    AutomationCreateRequest,
    AutomationKind,
    AutomationMetadata,
    AutomationTriggerType,
    AutomationUpdateRequest,
)

MetadataInput = AutomationMetadata | dict[str, Any]


def _path(automation_id: UUID | str) -> str:
    return f"/v1/automations/{quote(str(automation_id), safe='')}"


def _list_params(
    *,
    kind: AutomationKind | str | None,
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
    if isinstance(metadata, AutomationMetadata):
        return metadata.model_dump(mode="json", exclude_none=True)
    return metadata


def _create_body(
    *,
    name: str,
    trigger_type: AutomationTriggerType | str,
    description: str | None,
    cron_schedule: str | None,
    kind: AutomationKind | str | None,
    prompt: str | None,
    runtime_group_id: UUID | str | None,
    task_id: UUID | str | None,
    next_trigger_at: datetime | None,
    metadata: MetadataInput | None,
    enabled: bool | None,
) -> dict[str, Any]:
    return AutomationCreateRequest(
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
    return AutomationUpdateRequest(
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
