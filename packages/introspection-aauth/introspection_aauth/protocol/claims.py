"""AAuth's tokens' claims (`#tokens`): one model per token type, used both to
issue a token and to read one that verified. Each model checks what a token
must be on its own; whether it is the token a caller expected is the job of
an expectation's `failures`, which names every check that failed."""

from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import VerificationError
from .keys import Jwk, thumbprint
from .models import Budget

AGENT_DWK = "aauth-agent.json"
PERSON_DWK = "aauth-person.json"
ACCESS_DWK = "aauth-access.json"
RESOURCE_DWK = "aauth-resource.json"
#: The longest a person or auth token may live (`#person-token`, `#auth-token`).
MAX_TOKEN_LIFETIME_SECONDS = 3_600
#: The longest an agent token should live (`#agent-token`).
MAX_AGENT_TOKEN_LIFETIME_SECONDS = 86_400


class Confirmation(BaseModel):
    """`cnf`: the key a token is bound to (RFC 7800)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    jwk: Jwk

    @model_validator(mode="after")
    def _a_public_key(self) -> Self:
        try:
            thumbprint(self.jwk)
        except VerificationError as exc:
            raise ValueError(exc.detail) from None
        return self

    @property
    def thumbprint(self) -> str:
        return thumbprint(self.jwk)


class Claims(BaseModel):
    """What every AAuth token carries; a token type that caps its lifetime
    sets `max_lifetime`."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    max_lifetime: ClassVar[int | None] = None

    iss: str
    iat: int
    exp: int
    jti: str = Field(min_length=1)

    @model_validator(mode="after")
    def _a_bounded_life(self) -> Self:
        if self.exp <= self.iat:
            raise ValueError("exp is not after iat")
        cap = type(self).max_lifetime
        if cap is not None and self.exp - self.iat > cap:
            raise ValueError(f"the token's lifetime is over {cap} seconds")
        return self


class AgentTokenClaims(Claims):
    """`aa-agent+jwt` (`#agent-token`): the agent, and the key it signs with."""

    max_lifetime: ClassVar[int | None] = MAX_AGENT_TOKEN_LIFETIME_SECONDS

    dwk: Literal["aauth-agent.json"]
    #: `aauth:local@domain`.
    sub: str = Field(min_length=1)
    cnf: Confirmation
    #: The Person Server the agent's provider names for it, when it names one.
    ps: str | None = None


class PersonTokenClaims(Claims):
    """`aa-person+jwt` (`#person-token`): who the agent acts for, at one resource."""

    max_lifetime: ClassVar[int | None] = MAX_TOKEN_LIFETIME_SECONDS

    dwk: Literal["aauth-person.json"]
    aud: str
    #: The person's directed identifier at `aud`.
    sub: str = Field(min_length=1)
    cnf: Confirmation
    tenant: str | None = None
    mission_s256: str | None = None


class Carried(BaseModel):
    """The members a resource token asks for and an auth token carries over."""

    model_config = ConfigDict(frozen=True)

    scope: str | None = None
    budget: Budget | None = None
    mission_s256: str | None = None
    tenant: str | None = None
    account: str | None = None
    r3_uri: str | None = None
    r3_s256: str | None = None

    def scopes(self) -> set[str]:
        return set((self.scope or "").split())


class ResourceTokenClaims(Claims, Carried):
    """`aa-resource+jwt` (`#resource-token`): a call a resource asks to be
    authorized, for the server named in `aud`. It should live five minutes
    at most; a longer one is still read, since its resource bounds it."""

    dwk: Literal["aauth-resource.json"]
    aud: str
    ps: str | None = None
    sub: str | None = None
    agent_jkt: str | None = None
    #: The `jti` of the person token the resource saw.
    presented_jti: str | None = None


class AuthGrant(Carried):
    """What an auth token grants, read from the resource token that asked
    for it: the members an issuer carries over, and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aud: str
    sub: str = Field(min_length=1)

    @classmethod
    def requested(cls, rt: ResourceTokenClaims, sub: str) -> "AuthGrant":
        """What `rt` asks for, for the person `sub`."""
        return cls(
            aud=rt.iss.rstrip("/"),
            sub=sub,
            scope=rt.scope,
            budget=rt.budget,
            mission_s256=rt.mission_s256,
            tenant=rt.tenant,
            account=rt.account,
            r3_uri=rt.r3_uri,
            r3_s256=rt.r3_s256,
        )


class AuthTokenClaims(Claims, Carried):
    """`aa-auth+jwt` (`#auth-token`): a grant for one call, from a Person
    Server (`dwk` its document) or a resource's Access Server."""

    max_lifetime: ClassVar[int | None] = MAX_TOKEN_LIFETIME_SECONDS

    dwk: Literal["aauth-person.json", "aauth-access.json"]
    aud: str
    sub: str = Field(min_length=1)
    #: The Person Server the person is at.
    ps: str
    cnf: Confirmation

    @classmethod
    def issue(
        cls,
        grant: AuthGrant,
        *,
        iss: str,
        dwk: Literal["aauth-person.json", "aauth-access.json"],
        ps: str,
        jwk: Jwk,
        jti: str,
        iat: int,
        exp: int,
    ) -> "AuthTokenClaims":
        return cls(
            iss=iss,
            dwk=dwk,
            jti=jti,
            iat=iat,
            exp=exp,
            ps=ps,
            cnf=Confirmation(jwk=jwk),
            aud=grant.aud,
            sub=grant.sub,
            scope=grant.scope,
            budget=grant.budget,
            mission_s256=grant.mission_s256,
            tenant=grant.tenant,
            account=grant.account,
            r3_uri=grant.r3_uri,
            r3_s256=grant.r3_s256,
        )


class DeliveryExpectation(BaseModel):
    """What a Person Server expects of the auth token a resource's Access
    Server delivers (`#auth-token-delivery`), and the budget it sent: an
    auth token for exactly the call it asked for, granting no more."""

    model_config = ConfigDict(frozen=True)

    issuer: str
    ps: str
    rt: ResourceTokenClaims
    agent_jkt: str
    #: The earlier of the presented person token's and the agent token's
    #: `exp`, which the auth token may not outlive.
    not_after: int
    sent: Budget | None = None

    def failures(self, claims: AuthTokenClaims) -> list[str]:
        """The name of every check `claims` fails."""
        rt, sent, granted = self.rt, self.sent, claims.budget
        checks = {
            "dwk": claims.dwk != ACCESS_DWK,
            "iss": claims.iss != self.issuer,
            "aud": claims.aud.rstrip("/") != rt.iss.rstrip("/"),
            "cnf": claims.cnf.thumbprint != self.agent_jkt,
            "sub": claims.sub != rt.sub,
            "ps": claims.ps != self.ps,
            "mission_s256": claims.mission_s256 != rt.mission_s256,
            "tenant": claims.tenant != rt.tenant,
            "account": claims.account != rt.account,
            "r3_uri": claims.r3_uri != rt.r3_uri,
            "r3_s256": claims.r3_s256 != rt.r3_s256,
            "scope": not claims.scopes() <= rt.scopes(),
            "exp": claims.exp > self.not_after,
            "budget": (sent is None) != (granted is None)
            or (
                sent is not None
                and granted is not None
                and (
                    not sent.same_scale(granted)
                    or granted.amount > sent.amount
                )
            ),
        }
        return [name for name, failed in checks.items() if failed]


class PresentedExpectation(BaseModel):
    """What the person token a resource saw must be, read from the resource
    token that names it: issued by `ps` for that resource, bound to the
    agent's key, and the same person, mission and tenant."""

    model_config = ConfigDict(frozen=True)

    ps: str
    rt: ResourceTokenClaims

    def failures(self, presented: PersonTokenClaims) -> list[str]:
        rt = self.rt
        checks = {
            "iss": presented.iss != self.ps,
            "aud": presented.aud != rt.iss.rstrip("/"),
            "cnf": presented.cnf.thumbprint != rt.agent_jkt,
            "jti": presented.jti != rt.presented_jti,
            "sub": presented.sub != rt.sub,
            "mission_s256": presented.mission_s256 != rt.mission_s256,
            "tenant": presented.tenant != rt.tenant,
        }
        return [name for name, failed in checks.items() if failed]


class ResourceTokenExpectation(BaseModel):
    """What a resource token must say for the server it reached: that
    server as its `aud`, the Person Server it came through as its `ps`, the
    agent that presents it, and the members the server needs."""

    model_config = ConfigDict(frozen=True)

    ps: str
    aud: str | None = None
    agent_jkt: str | None = None
    tenant: str | None = None
    #: Whether `sub`, `presented_jti` and `agent_jkt` must be present.
    requires_presented: bool = False

    def failures(self, rt: ResourceTokenClaims) -> list[str]:
        checks = {
            "ps": (rt.ps or "").rstrip("/") != self.ps,
            "aud": self.aud is not None and rt.aud != self.aud,
            "agent_jkt": self.agent_jkt is not None
            and rt.agent_jkt != self.agent_jkt,
            "tenant": self.tenant is not None and rt.tenant != self.tenant,
            "sub": self.requires_presented and not rt.sub,
            "presented_jti": self.requires_presented and not rt.presented_jti,
            "agent_jkt_present": self.requires_presented and not rt.agent_jkt,
        }
        return [name for name, failed in checks.items() if failed]


class AgentExpectation(BaseModel):
    """What the agent token a Person Server forwards must be: bound to the
    key the resource token names, and for that Person Server if it names one."""

    model_config = ConfigDict(frozen=True)

    agent_jkt: str
    ps: str

    def failures(self, agent: AgentTokenClaims) -> list[str]:
        checks = {
            "cnf": agent.cnf.thumbprint != self.agent_jkt,
            "ps": agent.ps is not None and agent.ps.rstrip("/") != self.ps,
        }
        return [name for name, failed in checks.items() if failed]
