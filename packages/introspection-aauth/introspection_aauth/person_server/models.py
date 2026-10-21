"""What a Person Server keeps, and the requests it takes."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..protocol.models import Budget


class ApprovalKind(StrEnum):
    MISSION = "mission"
    AUTH_TOKEN = "auth_token"
    COMPLETION = "completion"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class LogEntry(BaseModel):
    """An update the agent logged under a mission."""

    at: int
    entry: str


class Mission(BaseModel):
    """What a person approved, keyed by the hash of its bytes."""

    s256: str
    #: The mission's bytes, as hashed and returned to the agent.
    mission: str
    agent_id: str
    #: Who the mission is for, as the `Directory` names them.
    person: str
    resources: list[str]
    budget: Budget | None = None
    spent: int = 0
    log: list[LogEntry] = Field(default_factory=list)
    expires_at: int
    completed_at: int | None = None


class Refusal(BaseModel):
    """How a federated request ended without an auth token."""

    status: int
    error: str
    detail: str


class Federation(BaseModel):
    """An auth token request redeemed at the resource's Access Server
    (`#ps-as-federation`)."""

    access_server: str
    resource_token: str
    agent_token: str
    presented_token: str
    #: The `budget` sent to the Access Server.
    budget: Budget | None = None
    #: Whether the spend must fit what is left; False once a person allowed it over.
    within_budget: bool = True
    #: The Access Server's `AAuth-Requirement` while it decides, relayed to the agent.
    requirement: str | None = None
    auth_token: str | None = None
    auth_token_expires_at: int | None = None
    collected: bool = False
    refusal: Refusal | None = None

    @property
    def settled(self) -> bool:
        return (
            self.auth_token is not None
            or self.collected
            or self.refusal is not None
        )


class Approval(BaseModel):
    """A decision this Person Server waits on; the host's app makes it."""

    id: str
    kind: ApprovalKind
    status: ApprovalStatus = ApprovalStatus.PENDING
    #: Bumped on each write, so a store can refuse a stale one.
    version: int = 0
    agent_id: str
    agent_jkt: str
    agent_jwk: dict[str, Any]
    person: str
    mission_s256: str | None = None
    #: The mission's description, the request's scope, or the completion summary.
    description: str
    #: The resource's own description of the request, from its R3 proposal.
    summary: str | None = None
    resource: str | None = None
    budget: Budget | None = None
    #: The claims an approved auth token is issued with.
    grant: dict[str, Any] = Field(default_factory=dict)
    federation: Federation | None = None
    decided_budget: Budget | None = None
    decided_by: str | None = None
    decided_at: int | None = None
    expires_at: int
    created_at: int


class MissionProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str = Field(min_length=1, max_length=8_000)
    resources: list[str] = Field(default_factory=list, max_length=16)
    tenant: str | None = None
    login_hint: str | None = Field(None, max_length=512)


class MissionAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    description: str | None = Field(None, max_length=8_000)
    summary: str | None = Field(None, max_length=8_000)
    tenant: str | None = None


class PersonTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource: str = Field(min_length=1, max_length=2_048)
    tenant: str | None = None
    login_hint: str | None = Field(None, max_length=512)
    mission_s256: str | None = None


class AuthTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_token: str
    presented_token: str
    tenant: str | None = None
    login_hint: str | None = Field(None, max_length=512)
    upstream_token: str | None = None
    subagent_token: str | None = None
