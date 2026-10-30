"""Pydantic mirrors of DP ``/v1/aauth``: the missions an agent works under
and the approvals a person decides (draft-hardt-oauth-aauth-protocol).

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ApproverIdentity(BaseModel):
    """The approver as the customer's app knows them: its own ``user_id``,
    or an ``anonymous_id`` for a visitor who has not signed in."""

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    anonymous_id: str | None = None

    @model_validator(mode="after")
    def _one_id(self) -> ApproverIdentity:
        if self.user_id is None and self.anonymous_id is None:
            raise ValueError("an approver needs a user_id or an anonymous_id")
        return self


class ApprovalDecider(BaseModel):
    """Who decided: a customer ``identity``, or a project ``member_id``."""

    model_config = ConfigDict(extra="forbid")

    identity: ApproverIdentity | None = None
    member_id: UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> ApprovalDecider:
        if (self.identity is None) == (self.member_id is None):
            raise ValueError(
                "a decider is an identity or a member_id, not both"
            )
        return self


class ApprovalDecision(BaseModel):
    """Body of ``PATCH /v1/aauth/approvals/{id}``: the approver's answer.
    ``budget`` grants less than the agent asked for; approving does what
    the agent asked."""

    model_config = ConfigDict(extra="forbid")

    status: ApprovalStatus
    decided_by: ApprovalDecider
    budget: Budget | None = None


__all__ = [
    "Approval",
    "ApprovalDecider",
    "ApprovalDecision",
    "ApprovalKind",
    "ApprovalStatus",
    "ApproverIdentity",
    "Budget",
    "Mission",
    "MissionLogEntry",
]
