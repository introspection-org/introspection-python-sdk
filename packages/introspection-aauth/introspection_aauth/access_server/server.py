"""An AAuth Access Server (`#access-server-federation`): a resource's own
policy over the auth tokens a Person Server redeems for it. A resource names
this server as the `aud` of its resource tokens; the person's Person Server,
having weighed the call against the person's mission, asks it for the auth
token here, and this server issues it or makes the Person Server wait."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Unpack

import httpx2 as httpx

from ..protocol import jwt
from ..protocol.errors import AAuthError, Answer, VerificationError
from ..protocol.httpsig import SignedRequest
from ..protocol.keys import SigningKey, thumbprint
from ..protocol.models import Budget
from ..protocol.server import (
    ACCESS_DWK,
    PERSON_DWK,
    RESOURCE_DWK,
    Server,
    ServerOptions,
    parse,
    pending,
    verify_agent_token,
    verify_server,
)
from .models import (
    AccessRequest,
    PendingAccess,
    PendingStatus,
    TokenRequest,
    Verdict,
)
from .store import MemoryStore, Store

Policy = Callable[[AccessRequest], Verdict | Awaitable[Verdict]]
#: Resource token claims an auth token carries over as they are.
CARRIED = ("account", "mission_s256", "tenant", "r3_uri", "r3_s256")


def _bad(token: str, detail: str) -> AAuthError:
    return AAuthError(400, f"invalid_{token}_token", detail)


def _narrowed(asked: str | None, scope: str | None) -> str | None:
    """`scope`, which may be no broader than what was asked."""
    if scope is None:
        return asked
    if not set(scope.split()) <= set((asked or "").split()):
        raise AAuthError(
            500,
            "server_error",
            "the policy granted a scope that was not asked for",
        )
    return scope


def _lowered(asked: Budget | None, granted: Budget | None) -> Budget | None:
    """`granted`, which may be no more than what was asked."""
    if granted is None:
        return asked
    if (
        asked is None
        or not asked.same_scale(granted)
        or granted.amount > asked.amount
    ):
        raise AAuthError(
            500, "server_error", "the policy granted more than was asked"
        )
    return granted


class AccessServer(Server):
    """Decides, by `policy`, for the `resources` it serves, taking requests
    only from `person_servers` for agents of `agent_providers`."""

    def __init__(
        self,
        issuer: str,
        signing_key: SigningKey,
        policy: Policy,
        *,
        resources: Sequence[str],
        person_servers: Sequence[str],
        agent_providers: Sequence[str],
        http: httpx.AsyncClient,
        store: Store | None = None,
        token_ttl: int = jwt.MAX_TOKEN_LIFETIME_SECONDS,
        pending_ttl: int = 86_400,
        on_pending: Callable[[PendingAccess], Awaitable[None]] | None = None,
        **options: Unpack[ServerOptions],
    ):
        super().__init__(issuer, ACCESS_DWK, signing_key, http, **options)
        self.policy = policy
        self.store: Store = store or MemoryStore()
        self._resources = {r.rstrip("/") for r in resources}
        self._person_servers = {p.rstrip("/") for p in person_servers}
        self._providers = {p.rstrip("/") for p in agent_providers}
        self._token_ttl = min(token_ttl, jwt.MAX_TOKEN_LIFETIME_SECONDS)
        self._pending_ttl = pending_ttl
        self._on_pending = on_pending

    def metadata(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            **({"name": self.name} if self.name else {}),
            "jwks_uri": f"{self.issuer}/.well-known/aauth-access-jwks.json",
            "auth_token_endpoint": f"{self.endpoint_base}/token",
        }

    def pending_url(self, pending_id: str) -> str:
        return f"{self.endpoint_base}/pending/{pending_id}"

    # region verification
    async def _resource_token(self, token: str, ps: str) -> dict[str, Any]:
        try:
            resource = str(jwt.decode(token).claims.get("iss", "")).rstrip("/")
        except VerificationError:
            raise _bad("resource", "not a JWT") from None
        # Checked before verifying, since verifying fetches its keys.
        if resource not in self._resources:
            raise _bad(
                "resource",
                f"this Access Server does not decide for {resource}",
            )
        try:
            rt = await self.discovery.verified(
                resource,
                RESOURCE_DWK,
                lambda keys: jwt.verify(
                    token, keys, jwt.RESOURCE_TOKEN, self.clock()
                ),
            )
        except VerificationError as exc:
            raise _bad("resource", exc.detail) from None
        if rt.get("dwk") != RESOURCE_DWK or rt.get("aud") != self.issuer:
            raise _bad(
                "resource", "not a resource token for this Access Server"
            )
        if rt.get("ps") != ps:
            raise _bad(
                "resource", "its ps is not the Person Server that sent it"
            )
        if any(
            not isinstance(rt.get(c), str) or not rt[c]
            for c in ("sub", "presented_jti", "agent_jkt")
        ):
            raise _bad(
                "resource", "sub, presented_jti and agent_jkt are required"
            )
        return rt

    async def _agent_token(
        self, token: str, rt: dict[str, Any], ps: str
    ) -> dict[str, Any]:
        try:
            claims = await verify_agent_token(
                token, self.discovery, self._providers, self.clock()
            )
        except VerificationError as exc:
            raise AAuthError(
                400, "invalid_request", f"agent_token: {exc.detail}"
            ) from None
        if thumbprint(claims["cnf"]["jwk"]) != rt["agent_jkt"]:
            raise _bad("resource", "agent_jkt is not the agent token's key")
        if "ps" in claims and str(claims["ps"]).rstrip("/") != ps:
            raise AAuthError(
                400,
                "invalid_request",
                "agent_token names another Person Server",
            )
        return claims

    async def _presented_token(
        self, token: str, rt: dict[str, Any], ps: str
    ) -> dict[str, Any]:
        """The person token the resource saw, from the Person Server that sent
        it, matching the resource token exactly. Step-up with an auth token this
        server issued is not served."""
        try:
            presented = await self.discovery.verified(
                ps,
                PERSON_DWK,
                lambda keys: jwt.verify(
                    token, keys, jwt.PERSON_TOKEN, self.clock()
                ),
            )
        except VerificationError as exc:
            code = (
                "expired_presented_token"
                if exc.code == "expired_jwt"
                else "invalid_presented_token"
            )
            raise AAuthError(400, code, exc.detail) from None
        cnf = presented.get("cnf")
        jwk = cnf.get("jwk") if isinstance(cnf, dict) else None
        if (
            presented.get("iss") != ps
            or presented.get("aud") != rt.get("iss")
            or not isinstance(jwk, dict)
            or thumbprint(jwk) != rt["agent_jkt"]
            or any(
                presented.get(c) != rt.get(r)
                for c, r in (
                    ("jti", "presented_jti"),
                    ("sub", "sub"),
                    ("mission_s256", "mission_s256"),
                    ("tenant", "tenant"),
                )
            )
        ):
            raise _bad("resource", "it does not match the presented token")
        return presented

    async def _summary(self, rt: dict[str, Any]) -> str | None:
        if not isinstance(rt.get("r3_uri"), str) or not isinstance(
            rt.get("r3_s256"), str
        ):
            return None
        try:
            proposal = await self.identity.read_proposal(
                self.http, rt["r3_uri"], rt["r3_s256"], self.clock()
            )
        except (httpx.HTTPError, ValueError):
            return None
        display = proposal.get("display")
        summary = display.get("summary") if isinstance(display, dict) else None
        return str(summary) if summary else None

    # endregion

    async def token(self, request: SignedRequest) -> Answer:
        """`POST /token`: a Person Server's signed request for an auth token."""
        ps = await verify_server(
            request,
            self.discovery,
            self._person_servers,
            PERSON_DWK,
            self.clock(),
        )
        body = parse(TokenRequest, request.body)
        if body.upstream_token is not None or body.subagent_token is not None:
            raise AAuthError(
                400,
                "invalid_request",
                "call chaining and sub-agents are not served here",
            )
        rt = await self._resource_token(body.resource_token, ps)
        agent = await self._agent_token(body.agent_token, rt, ps)
        presented = await self._presented_token(body.presented_token, rt, ps)
        rt_budget = (
            Budget.model_validate(rt["budget"])
            if rt.get("budget") is not None
            else None
        )
        sent = body.budget
        if (
            sent is not None
            and rt_budget is not None
            and (
                not sent.same_scale(rt_budget)
                or sent.amount > rt_budget.amount
            )
        ):
            raise AAuthError(
                400, "invalid_request", "budget is above the resource token's"
            )
        asked = AccessRequest(
            resource=str(rt["iss"]),
            ps=ps,
            sub=str(rt["sub"]),
            tenant=rt.get("tenant"),
            scope=rt.get("scope"),
            mission_s256=rt.get("mission_s256"),
            budget=sent or rt_budget,
            summary=await self._summary(rt),
            agent_id=str(agent["sub"]),
            agent_provider=str(agent["iss"]),
            agent_jkt=str(rt["agent_jkt"]),
            claims={
                "resource_token": rt,
                "agent_token": agent,
                "presented_token": presented,
            },
        )
        verdict = self.policy(asked)
        verdict = verdict if isinstance(verdict, Verdict) else await verdict
        grant = {
            "aud": rt["iss"],
            "ps": ps,
            "sub": rt["sub"],
            **{c: rt[c] for c in CARRIED if c in rt},
        }
        record = PendingAccess(
            id=self.new_id(),
            verdict=verdict,
            request=asked,
            grant=grant,
            jwk=agent["cnf"]["jwk"],
            not_after=min(int(agent["exp"]), int(presented["exp"])),
            created_at=self.clock(),
            expires_at=min(
                self.clock() + self._pending_ttl,
                int(agent["exp"]),
                int(presented["exp"]),
            ),
        )
        if verdict.decision == "allow":
            return self._issue(
                record,
                _narrowed(asked.scope, verdict.scope),
                _lowered(asked.budget, verdict.budget),
            )
        if verdict.decision == "deny":
            raise AAuthError(
                403,
                "denied",
                verdict.detail or "this resource's policy refuses it",
            )
        await self.store.put_pending(record)
        if self._on_pending is not None:
            await self._on_pending(record)
        return self._waiting(record)

    def _waiting(self, record: PendingAccess) -> Answer:
        verdict = record.verdict
        requirement = (
            f'requirement=interaction;url="{verdict.url}";code="{verdict.code}"'
            if verdict.decision == "interaction"
            else "requirement=approval"
        )
        return pending(
            self.pending_url(record.id), self.retry_after, requirement
        )

    def _issue(
        self, record: PendingAccess, scope: str | None, budget: Budget | None
    ) -> Answer:
        """An auth token, for no longer than an hour or the tokens it was asked with."""
        iat = self.clock()
        exp = min(iat + self._token_ttl, record.not_after)
        token = self.identity.token(
            {
                "iss": self.issuer,
                "dwk": ACCESS_DWK,
                "jti": self.new_id(),
                "iat": iat,
                "exp": exp,
                **record.grant,
                **({"scope": scope} if scope else {}),
                **({"budget": budget.model_dump()} if budget else {}),
                "cnf": {"jwk": record.jwk},
            },
            jwt.AUTH_TOKEN,
        )
        return Answer(200, {"auth_token": token, "expires_in": exp - iat})

    async def poll(self, request: SignedRequest, pending_id: str) -> Answer:
        """`GET /pending/{id}`: only the Person Server that asked may poll."""
        ps = await verify_server(
            request,
            self.discovery,
            self._person_servers,
            PERSON_DWK,
            self.clock(),
        )
        record = await self.store.pending(pending_id)
        if record is None or record.request.ps != ps:
            raise AAuthError(404, "not_found", "no such pending request")
        if record.status is PendingStatus.DENIED:
            raise AAuthError(
                403, "denied", "this resource's policy refuses it"
            )
        if record.status is PendingStatus.COLLECTED:
            raise AAuthError(
                410, "invalid_code", "its auth token was issued already"
            )
        if self.clock() >= record.expires_at:
            raise AAuthError(408, "expired", "nobody decided in time")
        if record.status is PendingStatus.PENDING:
            return self._waiting(record)
        collected = record.model_copy(
            update={
                "status": PendingStatus.COLLECTED,
                "version": record.version + 1,
            }
        )
        if not await self.store.transition_pending(record, collected):
            raise AAuthError(
                410, "invalid_code", "its auth token was issued already"
            )
        return self._issue(record, record.scope, record.budget)

    async def decide(
        self,
        pending_id: str,
        approved: bool,
        *,
        scope: str | None = None,
        budget: Budget | None = None,
        decided_by: str | None = None,
    ) -> PendingAccess:
        """Settle a request the policy waited on, once; approving may narrow
        the scope or lower the budget."""
        record = await self.store.pending(pending_id)
        if record is None:
            raise AAuthError(404, "not_found", "no such request")
        if record.status is not PendingStatus.PENDING:
            raise AAuthError(409, "invalid_request", "already decided")
        if self.clock() >= record.expires_at:
            raise AAuthError(410, "expired", "this request has expired")
        decided = record.model_copy(
            update={
                "status": PendingStatus.APPROVED
                if approved
                else PendingStatus.DENIED,
                "version": record.version + 1,
                "scope": _narrowed(record.request.scope, scope),
                "budget": _lowered(record.request.budget, budget),
                "decided_by": decided_by,
            }
        )
        if not await self.store.transition_pending(record, decided):
            raise AAuthError(409, "invalid_request", "already decided")
        return decided
