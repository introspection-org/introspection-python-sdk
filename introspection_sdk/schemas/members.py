"""Pydantic mirrors of CP `/v1/members` request/response models.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so CP additions don't break the SDK.

``tags`` and ``metadata`` are the two label sets a member carries, and
they differ in what they grant. A tag is **access-bearing**: a member
is admitted by every share whose ``granted_tag`` it holds (see
``runner.shares``), which is why writing one needs ``members:manage``.
The implicit grant to any file or task whose tags intersect the member's
still works but is being retired; share with a ``granted_tag`` instead.
Metadata **grants nothing**: it is a filter-only ``key: value`` map.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class MemberType(StrEnum):
    """What kind of principal a member is."""

    BUSINESS = "business"
    AGENT = "agent"
    CUSTOMER = "customer"


class Member(_ApiModel):
    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime
    email: str | None = None
    name: str | None = None
    external_user_id: str | None = None
    image_url: str | None = None
    role: str = "member"
    member_type: MemberType = MemberType.BUSINESS
    is_deactivated: bool = False
    tags: list[str] = []
    """Access-bearing tags: this member is admitted by every share whose
    ``granted_tag`` is one of these. The implicit grant to files and tasks
    whose tags intersect these is being retired."""
    metadata: dict[str, str] = {}
    """Customer-defined ``key: value`` labels. Grants nothing; filter on it
    with ``members.list(metadata=...)``."""
    application_idp_id: UUID | None = None
    connector_id: UUID | None = None
    integration_id: UUID | None = None
    is_external_credential_agent: bool = False


class MemberCreateRequest(_ApiModel):
    """Body of ``POST /v1/members``: invite a human (``business``) member."""

    email: str
    name: str
    """Full name — the server requires a first and a last name."""
    role: str | None = None
    tags: list[str] | None = None
    """Seed tags. Access-bearing, so setting any needs ``members:manage``."""
    metadata: dict[str, str] | None = None
    """Seed metadata. Keys are letters, digits, ``_`` and ``-``; values are
    non-empty strings; at most 64 entries per write."""


class MemberUpdateRequest(_ApiModel):
    """Body of ``PATCH /v1/members/{id}`` (requires ``members:manage``)."""

    name: str | None = None
    image_url: str | None = None
    role: str | None = None
    tags: list[str] | None = None
    """Replaces the tag list wholesale. ``None`` leaves tags untouched; ``[]``
    clears them."""
    metadata: dict[str, str] | None = None
    """Replaces the metadata map wholesale. ``None`` leaves it untouched;
    ``{}`` clears it."""


__all__ = [
    "Member",
    "MemberCreateRequest",
    "MemberType",
    "MemberUpdateRequest",
]
