"""What a Person Server keeps, and the requests it takes."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..protocol.claims import AuthGrant
from ..protocol.keys import Jwk
from ..protocol.models import Budget
from ..protocol.wire import Wire


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


class MissionGrant(BaseModel):
    """What a mission approval would grant: the resources it covers. A
    completion's grant is empty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resources: list[str] = Field(default_factory=list)


class Approval(BaseModel):
    """A decision this Person Server waits on; the host's app makes it."""

    id: str
    kind: ApprovalKind
    status: ApprovalStatus = ApprovalStatus.PENDING
    #: Bumped on each write, so a store can refuse a stale one.
    version: int = 0
    agent_id: str
    agent_jkt: str
    agent_jwk: Jwk
    #: When the agent token the request came with expires.
    agent_expires_at: int
    person: str
    mission_s256: str | None = None
    #: The mission's description, the request's scope, or the completion summary.
    description: str
    #: The resource's own description of the request, from its R3 proposal.
    summary: str | None = None
    resource: str | None = None
    budget: Budget | None = None
    #: For an auth token, what it is issued with; for a mission, its resources.
    grant: AuthGrant | MissionGrant = Field(
        default_factory=MissionGrant, union_mode="left_to_right"
    )
    federation: Federation | None = None
    #: Set once the agent collects the auth token it issued; a second collect is refused.
    collected: bool = False
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

    action: Literal["update", "completion"]
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


class MissionDocument(BaseModel):
    """The mission as approved: its bytes are what `s256` hashes and what the
    agent is handed (`#mission`). Its approval makes it, and so its hash, the
    mission's own; it names no person, since the agent and an audit read it."""

    model_config = ConfigDict(frozen=True)

    agent: str
    approval: str
    approved_at: str
    expires_at: str
    description: str
    approved_resources: list[str]
    budget: Budget | None = None

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


class MissionAnswer(Wire):
    """An approved mission: its hash, its bytes and a person token for each
    resource it covers."""

    s256: str
    mission: str
    person_tokens: dict[str, str]


class MissionLogged(Wire):
    """A logged update: the hash of the entry."""

    s256: str


#: Seconds between polls when the Access Server sends no usable `Retry-After`, and the bounds on it.
DEFAULT_DELAY, MIN_DELAY, MAX_DELAY = 5, 1, 300


class Step(StrEnum):
    ISSUED = "issued"
    PENDING = "pending"
    REFUSED = "refused"


class Outcome(BaseModel):
    """What one exchange with an Access Server came to."""

    step: Step
    auth_token: str | None = None
    auth_token_expires_at: int | None = None
    #: The budget the Access Server granted, from its auth token.
    granted: Budget | None = None
    #: Where to poll next; on a pending outcome, None sends the request again.
    location: str | None = None
    requirement: str | None = None
    retry_after: int | None = None
    refusal: Refusal | None = None

    @classmethod
    def refused(cls, status: int, error: str, detail: str) -> "Outcome":
        return cls(
            step=Step.REFUSED,
            refusal=Refusal(status=status, error=error, detail=detail),
        )

    @classmethod
    def unreachable(cls, detail: str) -> "Outcome":
        """`as_unreachable`: no verifiable answer from the Access Server."""
        return cls.refused(502, "as_unreachable", detail)

    def poll_delay(self) -> int:
        """`Retry-After`, 5 seconds when absent; never a hot loop, never a stall."""
        if self.retry_after is None:
            return DEFAULT_DELAY
        return min(max(self.retry_after, MIN_DELAY), MAX_DELAY)
