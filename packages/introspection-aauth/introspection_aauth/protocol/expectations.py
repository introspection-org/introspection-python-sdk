"""What a caller expects of a token beyond its being valid on its own: each
expectation names every check a token fails."""

from pydantic import BaseModel, ConfigDict

from introspection_aauth.protocol.claims import (
    ACCESS_DWK,
    AgentTokenClaims,
    AuthTokenClaims,
    PersonTokenClaims,
    ResourceTokenClaims,
)
from introspection_aauth.protocol.models import Budget


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
    """What the token a resource saw must be, read from the resource token
    that names it: a person token, or an auth token `ps` issued for an earlier
    call there, issued by `ps` for that resource, bound to the agent's key,
    and the same person, mission and tenant."""

    model_config = ConfigDict(frozen=True)

    ps: str
    rt: ResourceTokenClaims

    def failures(
        self, presented: PersonTokenClaims | AuthTokenClaims
    ) -> list[str]:
        rt = self.rt
        checks = {
            "iss": presented.iss != self.ps,
            "aud": presented.aud.rstrip("/") != rt.iss.rstrip("/"),
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
