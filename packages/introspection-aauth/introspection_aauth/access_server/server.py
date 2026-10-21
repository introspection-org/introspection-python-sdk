"""An AAuth Access Server (`#access-server-federation`): a resource's own
policy over the auth tokens a Person Server redeems for it. A resource names
this server as the `aud` of its resource tokens; the person's Person Server,
having weighed the call against the person's mission, asks it for the auth
token here, and this server issues it or makes the Person Server wait."""

from collections.abc import Awaitable, Sequence
from typing import Protocol, Unpack

import httpx2 as httpx

from ..protocol import jwt
from ..protocol.claims import (
    ACCESS_DWK,
    PERSON_DWK,
    AgentExpectation,
    AgentTokenClaims,
    AuthGrant,
    AuthTokenClaims,
    PersonTokenClaims,
    PresentedExpectation,
    ResourceTokenClaims,
    ResourceTokenExpectation,
)
from ..protocol.errors import AAuthError, Answer, VerificationError
from ..protocol.httpsig import SignedRequest
from ..protocol.keys import SigningKey
from ..protocol.models import Budget
from ..protocol.server import (
    Server,
    ServerOptions,
    parse,
    pending,
    presented_token_error,
    requirement,
    verify_agent_token,
    verify_resource_token,
    verify_server,
)
from ..protocol.wire import AccessServerMetadata, AuthTokenAnswer, TokenRequest
from .models import (
    AccessRequest,
    PendingAccess,
    PendingStatus,
    Verdict,
    VerifiedTokens,
)
from .store import MemoryStore, Store


class Policy(Protocol):
    """A resource's policy: its verdict on one request, now or awaited."""

    def __call__(
        self, request: AccessRequest, /
    ) -> Verdict | Awaitable[Verdict]: ...


class PendingHook(Protocol):
    """Told of each request the policy waits on."""

    def __call__(self, pending: PendingAccess, /) -> Awaitable[None]: ...


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
    if asked is None or not granted.at_most(asked):
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
        on_pending: PendingHook | None = None,
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

    def metadata(self) -> AccessServerMetadata:
        return AccessServerMetadata(
            issuer=self.issuer,
            name=self.name or None,
            jwks_uri=f"{self.issuer}/.well-known/aauth-access-jwks.json",
            auth_token_endpoint=f"{self.endpoint_base}/token",
        )

    def pending_url(self, pending_id: str) -> str:
        return f"{self.endpoint_base}/pending/{pending_id}"

    # region verification
    async def _resource_token(
        self, token: str, ps: str
    ) -> ResourceTokenClaims:
        try:
            _, unverified = jwt.peek(token)
        except VerificationError:
            raise _bad("resource", "not a JWT") from None
        resource = (unverified.iss or "").rstrip("/")
        # Checked before verifying, since verifying fetches its keys.
        if resource not in self._resources:
            raise _bad(
                "resource",
                f"this Access Server does not decide for {resource}",
            )
        return await verify_resource_token(
            token,
            self.discovery,
            resource,
            self.clock(),
            ResourceTokenExpectation(
                ps=ps, aud=self.issuer, requires_presented=True
            ),
        )

    async def _agent_token(
        self, token: str, rt: ResourceTokenClaims, ps: str
    ) -> AgentTokenClaims:
        try:
            claims = await verify_agent_token(
                token, self.discovery, self._providers, self.clock()
            )
        except VerificationError as exc:
            raise AAuthError(
                400, "invalid_request", f"agent_token: {exc.detail}"
            ) from None
        wrong = AgentExpectation(agent_jkt=rt.agent_jkt or "", ps=ps).failures(
            claims
        )
        if "cnf" in wrong:
            raise _bad("resource", "agent_jkt is not the agent token's key")
        if wrong:
            raise AAuthError(
                400,
                "invalid_request",
                "agent_token names another Person Server",
            )
        return claims

    async def _presented_token(
        self, token: str, rt: ResourceTokenClaims, ps: str
    ) -> PersonTokenClaims:
        """The person token the resource saw, from the Person Server that sent
        it, matching the resource token exactly. Step-up with an auth token this
        server issued is not served."""
        try:
            presented = await self.discovery.verified(
                ps,
                PERSON_DWK,
                lambda keys: jwt.verify(
                    token,
                    keys,
                    jwt.PERSON_TOKEN,
                    self.clock(),
                    PersonTokenClaims,
                ),
            )
        except VerificationError as exc:
            raise presented_token_error(exc) from None
        wrong = PresentedExpectation(ps=ps, rt=rt).failures(presented)
        if wrong:
            raise _bad(
                "resource",
                f"it does not match the presented token: {', '.join(wrong)}",
            )
        return presented

    async def _summary(self, rt: ResourceTokenClaims) -> str | None:
        if rt.r3_uri is None or rt.r3_s256 is None:
            return None
        try:
            proposal = await self.identity.read_proposal(
                self.http, rt.iss, rt.r3_uri, rt.r3_s256, self.clock()
            )
        except (httpx.HTTPError, ValueError):
            return None
        return proposal.display.summary if proposal.display else None

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
        sent, asked_budget = body.budget, rt.budget
        if (
            sent is not None
            and asked_budget is not None
            and not sent.at_most(asked_budget)
        ):
            raise AAuthError(
                400, "invalid_request", "budget is above the resource token's"
            )
        # Enforced by the resource token's expectation.
        sub, agent_jkt = rt.sub or "", rt.agent_jkt or ""
        asked = AccessRequest(
            resource=rt.iss,
            ps=ps,
            sub=sub,
            tenant=rt.tenant,
            scope=rt.scope,
            mission_s256=rt.mission_s256,
            budget=sent or asked_budget,
            summary=await self._summary(rt),
            agent_id=agent.sub,
            agent_provider=agent.iss,
            agent_jkt=agent_jkt,
            claims=VerifiedTokens(
                resource_token=rt,
                agent_token=agent,
                presented_token=presented,
            ),
        )
        verdict = self.policy(asked)
        verdict = verdict if isinstance(verdict, Verdict) else await verdict
        record = PendingAccess(
            id=self.new_id(),
            verdict=verdict,
            request=asked,
            grant=AuthGrant.requested(rt, sub),
            jwk=agent.cnf.jwk,
            not_after=min(agent.exp, presented.exp),
            created_at=self.clock(),
            expires_at=min(
                self.clock() + self._pending_ttl, agent.exp, presented.exp
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
        await self.store.insert_pending(record)
        if self._on_pending is not None:
            await self._on_pending(record)
        return self._waiting(record)

    def _waiting(self, record: PendingAccess) -> Answer:
        verdict = record.verdict
        waiting_on = (
            requirement("interaction", url=verdict.url, code=verdict.code)
            if verdict.decision == "interaction"
            else None
        )
        return pending(
            self.pending_url(record.id), self.retry_after, waiting_on
        )

    def _issue(
        self, record: PendingAccess, scope: str | None, budget: Budget | None
    ) -> Answer:
        """An auth token, for no longer than an hour or the tokens it was asked with."""
        iat = self.clock()
        exp = min(iat + self._token_ttl, record.not_after)
        claims = AuthTokenClaims.issue(
            record.grant.model_copy(
                update={"scope": scope or None, "budget": budget}
            ),
            iss=self.issuer,
            dwk=ACCESS_DWK,
            ps=record.request.ps,
            jwk=record.jwk,
            jti=self.new_id(),
            iat=iat,
            exp=exp,
        )
        token = self.identity.token(claims, jwt.AUTH_TOKEN)
        return Answer(
            200, AuthTokenAnswer(auth_token=token, expires_in=exp - iat)
        )

    async def poll(self, request: SignedRequest, pending_id: str) -> Answer:
        """`GET /pending/{id}`: only the Person Server that asked may poll."""
        ps = await verify_server(
            request,
            self.discovery,
            self._person_servers,
            PERSON_DWK,
            self.clock(),
        )
        record = await self.store.select_pending(pending_id)
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
        record = await self.store.select_pending(pending_id)
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
