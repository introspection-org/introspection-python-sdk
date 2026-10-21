"""Code shared by the sync and async twins in :mod:`introspection_sdk.resources.members`."""

from __future__ import annotations

import builtins
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from introspection_sdk.schemas.members import (
    MEMBER_CREATE_ADAPTER,
    BusinessMemberCreate,
    CustomerMemberCreate,
    MemberType,
    MemberUpdateRequest,
)


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
    member: BusinessMemberCreate | CustomerMemberCreate | dict[str, Any],
) -> dict[str, Any]:
    # `member_type` has a default, so `exclude_none` always keeps it.
    validated = MEMBER_CREATE_ADAPTER.validate_python(
        member.model_dump() if isinstance(member, BaseModel) else member
    )
    return validated.model_dump(mode="json", exclude_none=True)


def _update_body(
    *,
    name: str | None,
    image_url: str | None,
    role: str | None,
    tags: builtins.list[str] | None,
    metadata: dict[str, str] | None,
    policy_attributes: dict[str, Any] | None,
) -> dict[str, Any]:
    # `exclude_none` drops an omitted field but keeps an explicit [] / {},
    # which is what clears tags / metadata — both replace wholesale.
    return MemberUpdateRequest(
        name=name,
        image_url=image_url,
        role=role,
        tags=tags,
        metadata=metadata,
        policy_attributes=policy_attributes,
    ).model_dump(mode="json", exclude_none=True)
