"""What an Access Server decides on, and what it keeps while it waits."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..protocol.models import Budget


class AccessRequest(BaseModel):
    """A Person Server's token request, once its signature and all three
    tokens verify: what the resource's policy is asked."""

    #: The resource the auth token would be for: the resource token's `iss`.
    resource: str
    #: The Person Server that sent it, in whose namespace `sub` is.
    ps: str
    #: The person's directed identifier at the resource.
    sub: str
    #: The person's organisation at their Person Server; `(ps, tenant)` names it.
    tenant: str | None = None
    scope: str | None = None
    mission_s256: str | None = None
    #: What the call costs: the budget the Person Server sent, else the resource token's.
    budget: Budget | None = None
    #: The resource's one-line description of the call, from its R3 proposal.
    summary: str | None = None
    agent_id: str
    agent_provider: str
    agent_jkt: str
    #: The verified claims of each token, for anything else a policy reads.
    claims: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Verdict(BaseModel):
    """The policy's answer. `allow` may narrow the scope or lower the budget;
    `approval` and `interaction` wait until `AccessServer.decide`."""

    model_config = ConfigDict(frozen=True)

    decision: Literal["allow", "deny", "approval", "interaction"]
    scope: str | None = None
    budget: Budget | None = None
    detail: str | None = None
    url: str | None = None
    code: str | None = None

    @classmethod
    def allow(
        cls, scope: str | None = None, budget: Budget | None = None
    ) -> "Verdict":
        return cls(decision="allow", scope=scope, budget=budget)

    @classmethod
    def deny(cls, detail: str | None = None) -> "Verdict":
        return cls(decision="deny", detail=detail)

    @classmethod
    def approval(cls) -> "Verdict":
        return cls(decision="approval")

    @classmethod
    def interaction(cls, url: str, code: str) -> "Verdict":
        return cls(decision="interaction", url=url, code=code)


class PendingStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    #: Approved, and its auth token handed out: an auth token is collected once.
    COLLECTED = "collected"


class PendingAccess(BaseModel):
    """A request the policy is waiting on."""

    id: str
    status: PendingStatus = PendingStatus.PENDING
    version: int = 0
    verdict: Verdict
    request: AccessRequest
    #: The claims the auth token is issued with, once approved.
    grant: dict[str, Any]
    #: The agent's key the auth token binds.
    jwk: dict[str, Any]
    #: The latest the auth token may expire: its agent and presented tokens' `exp`.
    not_after: int
    scope: str | None = None
    budget: Budget | None = None
    decided_by: str | None = None
    created_at: int
    expires_at: int


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resource_token: str
    agent_token: str
    presented_token: str
    budget: Budget | None = None
    upstream_token: str | None = None
    subagent_token: str | None = None
