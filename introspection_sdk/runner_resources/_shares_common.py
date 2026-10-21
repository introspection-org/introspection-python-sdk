"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.shares`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from introspection_sdk.schemas.shares import (
    ShareCreateRequest,
    ShareResourceType,
    ShareUpdateRequest,
)


def _list_params(
    *,
    limit: int,
    cursor: str | None,
    resource_type: ShareResourceType | str | None,
    resource_id: str | None,
    granted_member_id: str | None,
    granted_tag: str | None,
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
        "granted_member_id": granted_member_id,
        "granted_tag": granted_tag,
        "created_by_me": created_by_me,
        "granted_to_me": granted_to_me,
    }


def _create_body(
    *,
    resource_type: ShareResourceType | str,
    resource_id: str,
    granted_member_id: str | None,
    granted_tag: str | None,
    visible_from: datetime | None,
) -> dict[str, Any]:
    # Loose public inputs (plain str / enum) are coerced by validation:
    # str -> ShareResourceType, str -> UUID for granted_member_id.
    return ShareCreateRequest.model_validate(
        {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "granted_member_id": granted_member_id,
            "granted_tag": granted_tag,
            "visible_from": visible_from,
        }
    ).model_dump(mode="json", exclude_none=True)


def _update_body(visible_from: datetime | None) -> dict[str, Any]:
    return ShareUpdateRequest(visible_from=visible_from).model_dump(
        mode="json"
    )
