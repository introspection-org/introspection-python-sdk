"""Pydantic mirrors of DP ``/v1/aauth``: the missions an agent works under
and the approvals a person decides (draft-hardt-oauth-aauth-protocol).

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ApprovalKind(StrEnum):
    """What an approval asks the person for."""

    MISSION = "mission"
    AUTH_TOKEN = "auth_token"
    COMPLETION = "completion"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class Budget(ApiModel):
    """An amount in ``unit``, scaled by ``10 ** decimals``."""

    amount: int
    unit: str
    decimals: int


class MissionLogEntry(ApiModel):
    at: str
    entry: str


class Mission(ApiModel):
    """A task a person approved an agent to carry out, with the resources
    and the budget it may spend."""

    id: UUID
    org_id: UUID
    project_id: UUID
    s256: str
    """The mission's hash, as the agent's tokens carry it."""
    mission: str
    agent_id: str
    member_id: UUID
    resources: list[str] = Field(default_factory=list)
    budget: Budget | None = None
    spent: int = 0
    log: list[MissionLogEntry] = Field(default_factory=list)
    expires_at: str
    completed_at: str | None = None
    created_at: str
    updated_at: str


class Approval(ApiModel):
    """A decision a person is asked to make for an agent: a mission, a
    token for a resource, or a mission's completion."""

    id: UUID
    org_id: UUID
    project_id: UUID
    kind: ApprovalKind | str
    status: ApprovalStatus | str
    agent_id: str
    member_id: UUID
    mission_id: UUID | None = None
    description: str
    resource: str | None = None
    budget: Budget | None = None
    summary: str | None = None
    decided_budget: Budget | None = None
    decided_by_member_id: UUID | None = None
    decided_at: str | None = None
    expires_at: str
    created_at: str
    updated_at: str


__all__ = [
    "Approval",
    "ApprovalKind",
    "ApprovalStatus",
    "Budget",
    "Mission",
    "MissionLogEntry",
]
