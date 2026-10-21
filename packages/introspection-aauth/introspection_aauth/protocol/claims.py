"""AAuth's tokens' claims (`#tokens`): one model per token type, used both to
issue a token and to read one that verified. Each model checks what a token
must be on its own; whether it is the token a caller expected is the job of
an expectation's `failures`, which names every check that failed."""

from typing import ClassVar, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from introspection_aauth.protocol.errors import VerificationError
from introspection_aauth.protocol.keys import Jwk, thumbprint
from introspection_aauth.protocol.models import Budget

AGENT_DWK = "aauth-agent.json"
#: The well-known document a Person Server or Access Server signs under.
ServerDwk = Literal["aauth-person.json", "aauth-access.json"]
PERSON_DWK: Final = "aauth-person.json"
ACCESS_DWK: Final = "aauth-access.json"
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
    def requested(cls, rt: ResourceTokenClaims, sub: str) -> Self:
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

    dwk: ServerDwk
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
        dwk: ServerDwk,
        ps: str,
        jwk: Jwk,
        jti: str,
        iat: int,
        exp: int,
    ) -> Self:
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
