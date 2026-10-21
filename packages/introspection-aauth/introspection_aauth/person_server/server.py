"""An AAuth Person Server (draft-hardt-oauth-aauth-protocol -11): missions,
person and auth tokens, budgets, approvals, and federation with a resource's
own Access Server. Framework-free: each method takes a `SignedRequest` and
returns an `Answer`, or raises `AAuthError`."""

import asyncio
import hashlib
import hmac
import logging
from collections.abc import Awaitable, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import Protocol, Unpack
from urllib.parse import quote, unquote

import httpx2 as httpx

from introspection_aauth.person_server.federation import AccessServerClient
from introspection_aauth.person_server.models import (
    Approval,
    ApprovalKind,
    ApprovalStatus,
    AuthTokenRequest,
    Federation,
    LogEntry,
    Mission,
    MissionAction,
    MissionAnswer,
    MissionDocument,
    MissionGrant,
    MissionLogged,
    MissionProposal,
    Outcome,
    PersonTokenRequest,
    Refusal,
    Step,
)
from introspection_aauth.person_server.store import (
    AnyoneDirectory,
    Directory,
    Store,
)
from introspection_aauth.protocol import jwt
from introspection_aauth.protocol.claims import (
    PERSON_DWK,
    RESOURCE_DWK,
    AuthGrant,
    AuthTokenClaims,
    Confirmation,
    PersonTokenClaims,
    PresentedExpectation,
    ResourceTokenClaims,
    ResourceTokenExpectation,
)
from introspection_aauth.protocol.errors import (
    AAuthError,
    AccessDenied,
    Answer,
    Denied,
    Expired,
    InvalidCode,
    InvalidRequest,
    InvalidToken,
    MissionNotFound,
    MissionTerminated,
    NotFound,
    ServerError,
    VerificationError,
)
from introspection_aauth.protocol.httpsig import SignedRequest
from introspection_aauth.protocol.keys import SigningKey, b64url, s256
from introspection_aauth.protocol.models import Agent, Budget
from introspection_aauth.protocol.server import (
    Server,
    ServerOptions,
    https_origin,
    parse,
    pending,
    verify_agent,
    verify_resource_token,
)
from introspection_aauth.protocol.wire import (
    AuthTokenAnswer,
    Empty,
    PersonServerMetadata,
    PersonTokenAnswer,
)

logger = logging.getLogger(__name__)


class Hook(Protocol):
    """Told of an approval in `tenant`: one a person must decide, or one
    its resource's Access Server must."""

    def __call__(
        self, tenant: str, approval: Approval, /
    ) -> Awaitable[None]: ...


class Sleep(Protocol):
    """Waits `seconds`; a durable host passes its own."""

    def __call__(self, seconds: float, /) -> Awaitable[None]: ...


class Exchange(Protocol):
    """One exchange with the Access Server."""

    def __call__(self) -> Awaitable[Outcome]: ...


def _fits(mission: Mission, budget: Budget | None) -> bool:
    """Whether a request is within what is left of its mission's budget."""
    if budget is None:
        return True
    if mission.budget is None:
        return False
    left = mission.budget.model_copy(
        update={"amount": mission.budget.amount - mission.spent}
    )
    return budget.at_most(left)


class _Stale(Exception):
    """Rolls a `record` back: the approval changed or lapsed meanwhile."""


class PersonServer(Server):
    """Speaks for the people its `Directory` names, keeping its state in a `Store`.

    `subject_secret` keys each person's directed `sub` and is kept apart from
    the signing key, so rotating the key changes no one's identifier.
    `on_approval` is told of each approval a person must decide; `on_federate`
    of each approved request its resource's Access Server must decide, which
    the host runs with `federate` or journals step by step. Unset, it is
    run in this process.
    """

    def __init__(
        self,
        issuer: str,
        signing_key: SigningKey,
        store: Store,
        *,
        subject_secret: bytes,
        agent_providers: Sequence[str],
        http: httpx.AsyncClient,
        directory: Directory | None = None,
        default_tenant: str | None = None,
        token_ttl: int = 3_600,
        mission_ttl: int = 14 * 86_400,
        approval_ttl: int = 2 * 86_400,
        on_approval: Hook | None = None,
        on_federate: Hook | None = None,
        **options: Unpack[ServerOptions],
    ):
        super().__init__(issuer, PERSON_DWK, signing_key, http, **options)
        self.store = store
        self.directory = directory or AnyoneDirectory()
        self._subject_secret = subject_secret
        self._providers = {p.rstrip("/") for p in agent_providers}
        self._default_tenant = default_tenant
        self._token_ttl = min(token_ttl, jwt.MAX_TOKEN_LIFETIME_SECONDS)
        self._mission_ttl = mission_ttl
        self._approval_ttl = approval_ttl
        self._on_approval, self._on_federate = on_approval, on_federate
        self._running: set[asyncio.Task[Step | None]] = set()

    # region documents
    def metadata(self) -> PersonServerMetadata:
        return PersonServerMetadata(
            issuer=self.issuer,
            name=self.name,
            jwks_uri=f"{self.issuer}/.well-known/aauth-person-jwks.json",
            person_token_endpoint=f"{self.endpoint_base}/person-token",
            auth_token_endpoint=f"{self.endpoint_base}/token",
            mission_endpoint=f"{self.endpoint_base}/mission",
            claims_supported=["sub", "tenant"],
        )

    def access_server_client(self) -> AccessServerClient:
        """A client for the Access Servers it federates with, signing as it."""
        return AccessServerClient(
            self.identity, self.discovery, self.http, self.clock
        )

    def pending_url(self, tenant: str, approval_id: str) -> str:
        return f"{self.endpoint_base}/pending/{quote(tenant, safe='')}/{approval_id}"

    def pending_parts(self, path: str) -> tuple[str, str] | None:
        """The tenant and approval a pending URL's path after `/pending/`
        names, or None: the inverse of `pending_url`, so a host overriding
        one overrides both."""
        tenant, _, approval_id = path.rpartition("/")
        if not tenant or not approval_id or "/" in tenant:
            return None
        return unquote(tenant), approval_id

    # endregion

    # region people and tokens
    def directed_subject(self, person: str, audience: str) -> str:
        """The person's identifier at one audience; no two audiences can correlate it."""
        message = f"{person}\n{audience}".encode()
        return b64url(
            hmac.new(self._subject_secret, message, hashlib.sha256).digest()
        )

    # endregion

    # region missions
    async def propose_mission(self, request: SignedRequest) -> Answer:
        """`POST /mission`: always put to a person, who sets the budget."""
        agent = await self._agent(request)
        proposal = parse(MissionProposal, request.body)
        tenant = self._tenant(proposal.tenant)
        resources = [
            r.rstrip("/") for r in proposal.resources if https_origin(r)
        ]
        person = await self._person(tenant, agent, proposal.login_hint)
        approval = self._new_approval(
            ApprovalKind.MISSION,
            agent,
            person,
            proposal.description,
            grant=MissionGrant(resources=resources),
        )
        await self.store.insert_approval(tenant, approval)
        return await self._ask(tenant, approval)

    async def mission_action(
        self, request: SignedRequest, mission_s256: str
    ) -> Answer:
        """`POST /mission/{s256}`: log an update, or propose the mission complete."""
        agent = await self._agent(request)
        action = parse(MissionAction, request.body)
        tenant = self._tenant(action.tenant)
        mission = self._live(
            await self.store.select_mission(tenant, mission_s256), agent.id
        )
        if action.action == "update":
            entry = action.description or ""
            if not await self.store.update_mission_log(
                tenant,
                mission.s256,
                LogEntry(at=self.clock(), entry=entry),
                self.clock(),
            ):
                raise MissionTerminated("the mission has ended")
            return Answer(200, MissionLogged(s256=s256(entry.encode())))
        approval = self._new_approval(
            ApprovalKind.COMPLETION,
            agent,
            mission.person,
            action.summary or "The agent says the mission is done",
            mission_s256=mission.s256,
        )
        await self.store.insert_approval(tenant, approval)
        return await self._ask(tenant, approval)

    async def person_token(self, request: SignedRequest) -> Answer:
        """`POST /person-token`: who the agent acts for, at one resource."""
        agent = await self._agent(request)
        body = parse(PersonTokenRequest, request.body)
        tenant = self._tenant(body.tenant)
        resource = body.resource.rstrip("/")
        if not https_origin(resource):
            raise InvalidRequest("resource is an https origin")
        person = await self._person(tenant, agent, body.login_hint)
        mission = None
        if body.mission_s256 is not None:
            mission = self._live(
                await self.store.select_mission(tenant, body.mission_s256),
                agent.id,
            )
            if mission.person != person:
                raise MissionNotFound("no such mission")
        return Answer(
            200, self._person_token(tenant, agent, person, resource, mission)
        )

    # endregion

    # region auth tokens
    async def auth_token(self, request: SignedRequest) -> Answer:
        """`POST /token`: a call to a resource, weighed against the mission's budget."""
        agent = await self._agent(request)
        body = parse(AuthTokenRequest, request.body)
        tenant = self._tenant(body.tenant)
        presented = self._presented(body.presented_token)
        if presented.tenant != tenant:
            raise InvalidToken("resource", "tenant does not match")
        rt, mission = await self._resource_token(
            body.resource_token, tenant, agent
        )
        resource = rt.iss.rstrip("/")
        if PresentedExpectation(ps=self.issuer, rt=rt).failures(presented):
            raise InvalidToken(
                "resource", "does not match the presented token"
            )
        if rt.sub is None:
            raise InvalidToken("resource", "sub is required")
        budget = rt.budget
        grant = AuthGrant.requested(rt, rt.sub)
        access_server = self._access_server(rt)
        if access_server is not None:
            if (
                body.upstream_token is not None
                or body.subagent_token is not None
            ):
                raise InvalidRequest(
                    "call chaining and sub-agents are not federated here"
                )
            federation = Federation(
                access_server=access_server,
                resource_token=body.resource_token,
                agent_token=agent.token,
                presented_token=body.presented_token,
                budget=budget,
                within_budget=_fits(mission, budget),
            )
            return await self._federated(
                tenant, agent, mission, grant, federation
            )
        if budget is None:
            return Answer(200, self._auth_token(tenant, agent, grant, mission))
        if mission.budget is not None and mission.budget.same_scale(budget):
            spent = await self.store.update_spend(
                tenant, mission.s256, budget.amount, True, self.clock()
            )
            if spent is not None:
                return Answer(
                    200, self._auth_token(tenant, agent, grant, spent)
                )
        approval = self._new_approval(
            ApprovalKind.AUTH_TOKEN,
            agent,
            mission.person,
            rt.scope or "a request",
            mission_s256=mission.s256,
            resource=resource,
            budget=budget,
            grant=grant,
        )
        await self.store.insert_approval(tenant, approval)
        return await self._ask(tenant, approval)

    # endregion

    # region approvals
    async def poll(
        self, request: SignedRequest, tenant: str, approval_id: str
    ) -> Answer:
        """`GET /pending/{tenant}/{id}`: only the key that asked may read it."""
        agent = await self._agent(request)
        approval = await self.store.select_approval(tenant, approval_id)
        if approval is None or approval.agent_jkt != agent.jkt:
            raise NotFound("no such pending request")
        mission = (
            await self.store.select_mission(tenant, approval.mission_s256)
            if approval.mission_s256
            else None
        )
        if approval.collected:
            raise InvalidCode("this request was already answered")
        federation = approval.federation
        if approval.status is ApprovalStatus.DENIED:
            await self._answered(tenant, approval)
            refusal = federation.refusal if federation else None
            if refusal is not None:
                raise AAuthError(refusal.status, refusal.error, refusal.detail)
            raise Denied("the approver declined")
        if approval.status is ApprovalStatus.PENDING:
            if approval.expires_at <= self.clock():
                await self._answered(tenant, approval)
                raise Expired("nobody answered in time")
            return pending(
                self.pending_url(tenant, approval.id), self.retry_after
            )
        if federation is not None:
            return await self._collect(
                tenant, agent, approval, federation, mission
            )
        if approval.expires_at <= self.clock():
            await self._answered(tenant, approval)
            raise Expired("it was not collected in time")
        if approval.kind is ApprovalKind.COMPLETION:
            await self._answered(tenant, approval)
            return Answer(200, Empty())
        mission = self._live(mission, agent.id)
        if approval.kind is ApprovalKind.MISSION:
            await self._answered(tenant, approval)
            person_tokens = {
                r: self._person_token(
                    tenant, agent, mission.person, r, mission
                ).person_token
                for r in mission.resources
            }
            return Answer(
                200,
                MissionAnswer(
                    s256=mission.s256,
                    mission=b64url(mission.mission.encode()),
                    person_tokens=person_tokens,
                ),
            )
        if not isinstance(approval.grant, AuthGrant):
            raise ServerError("the approval grants nothing")
        await self._answered(tenant, approval)
        return Answer(
            200, self._auth_token(tenant, agent, approval.grant, mission)
        )

    async def decide(
        self,
        tenant: str,
        approval_id: str,
        status: ApprovalStatus,
        *,
        decided_by: str,
        budget: Budget | None = None,
        store: Store | None = None,
    ) -> Approval | None:
        """Record a person's answer, and do what was asked: create the mission,
        spend the call, or complete the mission. None if there is no such approval.

        With `store`, the decision is made in that unit of work, which the
        caller commits and then calls `decided`; otherwise in a transaction of
        its own, which `decided` follows."""
        if status is ApprovalStatus.PENDING:
            raise InvalidRequest("status is approved or denied", status=422)
        if store is not None:
            return await self._decide(
                store,
                tenant,
                approval_id,
                status,
                decided_by=decided_by,
                budget=budget,
            )
        async with self.store.transaction() as tx:
            decided = await self._decide(
                tx,
                tenant,
                approval_id,
                status,
                decided_by=decided_by,
                budget=budget,
            )
        if decided is not None:
            await self.decided(tenant, decided)
        return decided

    async def decided(self, tenant: str, approval: Approval) -> None:
        """After an approval is approved: a federated request goes to its Access Server."""
        if (
            approval.federation is None
            or approval.federation.settled
            or approval.status is not ApprovalStatus.APPROVED
        ):
            return
        if self._on_federate is not None:
            await self._on_federate(tenant, approval)
            return
        task = asyncio.create_task(self.federate(tenant, approval.id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def describe(self, tenant: str, approval_id: str) -> Approval | None:
        """Read a call's R3 proposal into its approval's `summary`, for whoever decides."""
        approval = await self.store.select_approval(tenant, approval_id)
        grant = approval.grant if approval is not None else None
        if (
            approval is None
            or not isinstance(grant, AuthGrant)
            or grant.r3_uri is None
            or grant.r3_s256 is None
        ):
            return approval
        summary = await self.identity.summary(
            self.http, grant.aud, grant.r3_uri, grant.r3_s256, self.clock()
        )
        if summary is None or not await self.store.update_approval_summary(
            tenant, approval.id, summary
        ):
            return approval
        return approval.model_copy(update={"summary": summary})

    # endregion

    # region federation

    async def federation_due(
        self, tenant: str, approval_id: str
    ) -> tuple[Federation, str] | None:
        """The federation still to run for an approval, and the agent's key thumbprint."""
        approval = await self.store.select_approval(tenant, approval_id)
        if (
            approval is None
            or approval.federation is None
            or approval.federation.settled
            or approval.status is not ApprovalStatus.APPROVED
        ):
            return None
        return approval.federation, approval.agent_jkt

    async def record_federation(
        self, tenant: str, approval_id: str, outcome: Outcome
    ) -> bool:
        """Record what the Access Server answered; whether to keep polling. The
        spend lands only when it issues, in the same transaction as its token."""
        try:
            return await self._record_federation(tenant, approval_id, outcome)
        except _Stale:
            return False

    async def federate(
        self,
        tenant: str,
        approval_id: str,
        sleep: Sleep = asyncio.sleep,
    ) -> Step | None:
        """Redeem an approved request at its Access Server, polling while it decides."""
        found = await self.federation_due(tenant, approval_id)
        if found is None:
            return None
        federation, agent_jkt = found
        client = self.access_server_client()
        metadata = await client.discover(federation.access_server)

        async def attempt(call: Exchange) -> Outcome:
            """`call`, or `as_unreachable` when the Access Server cannot be
            reached; retrying a connection is the http client's transport's."""
            try:
                return await call()
            except httpx.TransportError as exc:
                return Outcome.unreachable(f"it could not be reached: {exc}")

        outcome = (
            metadata
            if isinstance(metadata, Outcome)
            else await attempt(
                partial(client.request, federation, agent_jkt, metadata)
            )
        )
        while True:
            waiting = await self.record_federation(
                tenant, approval_id, outcome
            )
            if not waiting or isinstance(metadata, Outcome):
                return outcome.step
            await sleep(outcome.poll_delay())
            federation = federation.model_copy(
                update={"requirement": outcome.requirement}
            )
            outcome = await attempt(
                partial(client.request, federation, agent_jkt, metadata)
                if outcome.location is None
                else partial(
                    client.poll,
                    outcome.location,
                    federation,
                    agent_jkt,
                    metadata,
                )
            )

    # endregion

    # region private

    def _tenant(self, named: str | None) -> str:
        tenant = named or self._default_tenant
        if not tenant:
            raise InvalidRequest("name the tenant")
        return tenant

    async def _agent(self, request: SignedRequest) -> Agent:
        agent = await verify_agent(
            request, self.discovery, self._providers, self.clock()
        )
        if (
            agent.person_server is not None
            and agent.person_server != self.issuer
        ):
            raise InvalidRequest(
                "this agent's Person Server is another", status=403
            )
        return agent

    async def _person(
        self, tenant: str, agent: Agent, login_hint: str | None
    ) -> str:
        """Who the agent acts for. A key is bound to the first person it names."""
        if login_hint is None:
            bound = await self.store.select_binding(tenant, agent.jkt)
            if bound is None:
                raise InvalidRequest("name the person: login_hint")
            return bound
        person = self.directory.person(login_hint, tenant)
        if person is None:
            raise AccessDenied("this Person Server does not speak for them")
        if (
            await self.store.insert_binding(tenant, agent.jkt, person)
            != person
        ):
            raise InvalidRequest(
                "this agent acts for another person", status=403
            )
        return person

    def _expiry(self, agent: Agent, not_after: int | None = None) -> int:
        bounds = [self.clock() + self._token_ttl, agent.expires_at]
        return min([*bounds, not_after] if not_after is not None else bounds)

    def _person_token(
        self,
        tenant: str,
        agent: Agent,
        person: str,
        resource: str,
        mission: Mission | None,
    ) -> PersonTokenAnswer:
        now = self.clock()
        expires_at = self._expiry(
            agent, mission.expires_at if mission else None
        )
        claims = PersonTokenClaims(
            iss=self.issuer,
            dwk=PERSON_DWK,
            jti=self.new_id(),
            iat=now,
            exp=expires_at,
            aud=resource,
            sub=self.directed_subject(person, resource),
            cnf=Confirmation(jwk=agent.jwk),
            tenant=tenant,
            mission_s256=mission.s256 if mission else None,
        )
        return PersonTokenAnswer(
            person_token=self.identity.token(claims, jwt.PERSON_TOKEN),
            expires_in=expires_at - now,
        )

    def _auth_token(
        self,
        tenant: str,
        agent: Agent,
        grant: AuthGrant,
        mission: Mission,
    ) -> AuthTokenAnswer:
        now = self.clock()
        expires_at = self._expiry(agent, mission.expires_at)
        claims = AuthTokenClaims.issue(
            grant.model_copy(
                update={"tenant": tenant, "mission_s256": mission.s256}
            ),
            iss=self.issuer,
            dwk=PERSON_DWK,
            ps=self.issuer,
            jwk=agent.jwk,
            jti=self.new_id(),
            iat=now,
            exp=expires_at,
        )
        return AuthTokenAnswer(
            auth_token=self.identity.token(claims, jwt.AUTH_TOKEN),
            expires_in=expires_at - now,
        )

    def _live(self, mission: Mission | None, agent_id: str) -> Mission:
        """The mission, if it is this agent's and live; the same 404 otherwise."""
        if mission is None or mission.agent_id != agent_id:
            raise MissionNotFound("no such mission")
        if mission.completed_at is not None:
            raise MissionTerminated("mission completed")
        if mission.expires_at <= self.clock():
            raise MissionTerminated("mission expired")
        return mission

    def _presented(self, token: str) -> PersonTokenClaims:
        """The presented person token; an expired one is refused before anything is federated."""
        try:
            return self.identity.verify_own(
                token, jwt.PERSON_TOKEN, self.clock(), PersonTokenClaims
            )
        except VerificationError as exc:
            raise InvalidToken.rejected("presented", exc) from None

    async def _resource_token(
        self, token: str, tenant: str, agent: Agent
    ) -> tuple[ResourceTokenClaims, Mission]:
        """The resource token, verified against its resource's keys, and the
        live mission it falls under; only a mission's resources are fetched."""
        try:
            header, unverified = jwt.peek(token)
        except VerificationError:
            raise InvalidToken("resource", "not a JWT") from None
        if header.typ != jwt.RESOURCE_TOKEN or unverified.dwk != RESOURCE_DWK:
            raise InvalidToken("resource", "not a resource token")
        if unverified.tenant != tenant:
            raise InvalidToken("resource", "tenant does not match")
        if unverified.mission_s256 is None:
            raise AccessDenied("an auth token is issued only within a mission")
        mission = self._live(
            await self.store.select_mission(tenant, unverified.mission_s256),
            agent.id,
        )
        resource = (unverified.iss or "").rstrip("/")
        if resource not in mission.resources:
            raise AccessDenied("this mission does not cover that resource")
        rt = await verify_resource_token(
            token,
            self.discovery,
            resource,
            self.clock(),
            ResourceTokenExpectation(ps=self.issuer, agent_jkt=agent.jkt),
        )
        return rt, mission

    def _access_server(self, rt: ResourceTokenClaims) -> str | None:
        """The resource's own Access Server, when `aud` is not this Person Server."""
        if rt.aud == self.issuer:
            return None
        if not https_origin(rt.aud):
            raise InvalidToken(
                "resource",
                "aud is neither this Person Server nor an Access Server",
            )
        return rt.aud.rstrip("/")

    async def _federated(
        self,
        tenant: str,
        agent: Agent,
        mission: Mission,
        grant: AuthGrant,
        federation: Federation,
    ) -> Answer:
        """The mission and budget are weighed first, as for any resource: a
        request they cover is approved here and redeemed at the Access Server;
        one over what is left goes to a person first."""
        approval = self._new_approval(
            ApprovalKind.AUTH_TOKEN,
            agent,
            mission.person,
            grant.scope or "a request",
            mission_s256=mission.s256,
            resource=grant.aud,
            budget=federation.budget,
            grant=grant,
            federation=federation,
        )
        if not federation.within_budget:
            await self.store.insert_approval(tenant, approval)
            return await self._ask(tenant, approval)
        approval = approval.model_copy(
            update={
                "status": ApprovalStatus.APPROVED,
                "decided_at": self.clock(),
            }
        )
        await self.store.insert_approval(tenant, approval)
        await self.decided(tenant, approval)
        return pending(self.pending_url(tenant, approval.id), self.retry_after)

    def _new_approval(
        self,
        kind: ApprovalKind,
        agent: Agent,
        person: str,
        description: str,
        *,
        mission_s256: str | None = None,
        resource: str | None = None,
        budget: Budget | None = None,
        grant: AuthGrant | MissionGrant | None = None,
        federation: Federation | None = None,
    ) -> Approval:
        now = self.clock()
        return Approval(
            id=self.new_id(),
            kind=kind,
            agent_id=agent.id,
            agent_jkt=agent.jkt,
            agent_jwk=agent.jwk,
            agent_expires_at=agent.expires_at,
            person=person,
            description=description,
            mission_s256=mission_s256,
            resource=resource,
            budget=budget,
            grant=grant or MissionGrant(),
            federation=federation,
            expires_at=now + self._approval_ttl,
            created_at=now,
        )

    async def _ask(self, tenant: str, approval: Approval) -> Answer:
        if self._on_approval is not None:
            await self._on_approval(tenant, approval)
        return pending(self.pending_url(tenant, approval.id), self.retry_after)

    async def _answered(self, tenant: str, approval: Approval) -> None:
        """Record that a pending request got its terminal answer, once: its
        pending URL then answers `410` (`#pending-url-security`)."""
        answered = approval.model_copy(
            update={"collected": True, "version": approval.version + 1}
        )
        if not await self.store.transition_approval(
            tenant, approval, answered
        ):
            raise InvalidCode("this request was already answered")

    async def _collect(
        self,
        tenant: str,
        agent: Agent,
        approval: Approval,
        federation: Federation,
        mission: Mission | None,
    ) -> Answer:
        """The Access Server's auth token, collected once; else still waiting on it."""
        now = self.clock()
        if federation.collected:
            raise InvalidCode(
                "this request's auth token was already collected"
            )
        if federation.auth_token is None:
            if approval.expires_at <= now:
                await self._answered(tenant, approval)
                raise Expired("the Access Server did not answer in time")
            return pending(
                self.pending_url(tenant, approval.id),
                self.retry_after,
                federation.requirement,
            )
        self._live(mission, agent.id)
        expires_in = (federation.auth_token_expires_at or 0) - now
        if expires_in <= 0:
            await self._answered(tenant, approval)
            raise Expired("the auth token expired before it was collected")
        collected = federation.model_copy(
            update={
                "auth_token": None,
                "auth_token_expires_at": None,
                "collected": True,
            }
        )
        changed = approval.model_copy(
            update={"federation": collected, "version": approval.version + 1}
        )
        if not await self.store.transition_approval(tenant, approval, changed):
            raise InvalidCode(
                "this request's auth token was already collected"
            )
        return Answer(
            200,
            AuthTokenAnswer(
                auth_token=federation.auth_token, expires_in=expires_in
            ),
        )

    async def _decide(
        self,
        tx: Store,
        tenant: str,
        approval_id: str,
        status: ApprovalStatus,
        *,
        decided_by: str,
        budget: Budget | None,
    ) -> Approval | None:
        approval = await tx.select_approval(tenant, approval_id)
        if approval is None:
            return None
        if approval.kind is not ApprovalKind.MISSION and budget is not None:
            raise InvalidRequest("only a mission takes a budget", status=422)
        if (
            approval.kind is ApprovalKind.COMPLETION
            and decided_by != approval.person
        ):
            raise AccessDenied(
                "a completion is accepted by the person the mission is for"
            )
        now = self.clock()
        if (
            approval.status is not ApprovalStatus.PENDING
            or approval.expires_at <= now
        ):
            raise InvalidRequest(
                "this approval is already decided or has expired", status=409
            )
        mission_s256 = approval.mission_s256
        if status is ApprovalStatus.APPROVED:
            mission_s256 = await self._carry_out(
                tx, tenant, approval, budget, now
            )
        decided = approval.model_copy(
            update={
                "status": status,
                "version": approval.version + 1,
                "mission_s256": mission_s256,
                "decided_budget": budget,
                "decided_by": decided_by,
                "decided_at": now,
            }
        )
        if not await tx.transition_approval(tenant, approval, decided):
            raise InvalidRequest(
                "this approval is already decided or has expired", status=409
            )
        return decided

    async def _carry_out(
        self,
        tx: Store,
        tenant: str,
        approval: Approval,
        budget: Budget | None,
        now: int,
    ) -> str | None:
        if approval.kind is ApprovalKind.MISSION:
            expires_at = now + self._mission_ttl
            resources = (
                list(approval.grant.resources)
                if isinstance(approval.grant, MissionGrant)
                else []
            )
            blob = MissionDocument(
                agent=approval.agent_id,
                approval=approval.id,
                approved_at=datetime.fromtimestamp(now, UTC).isoformat(),
                expires_at=datetime.fromtimestamp(expires_at, UTC).isoformat(),
                description=approval.description,
                approved_resources=resources,
                budget=budget,
            ).to_json()
            mission = Mission(
                s256=s256(blob.encode()),
                mission=blob,
                agent_id=approval.agent_id,
                person=approval.person,
                resources=resources,
                budget=budget,
                expires_at=expires_at,
            )
            if not await tx.insert_mission(tenant, mission):
                raise InvalidRequest(
                    "a mission with this hash exists already", status=409
                )
            return mission.s256
        if approval.mission_s256 is None:
            return None
        current = await tx.select_mission(tenant, approval.mission_s256)
        if approval.kind is ApprovalKind.COMPLETION:
            ended = await tx.update_mission_end(
                tenant, approval.mission_s256, now
            )
        else:
            # A call in another unit than the mission's budget is approved without
            # spending; a federated one is spent once its Access Server issues.
            spend = (
                approval.budget.amount
                if approval.federation is None
                and approval.budget is not None
                and current is not None
                and current.budget is not None
                and current.budget.same_scale(approval.budget)
                else None
            )
            ended = await tx.update_spend(
                tenant, approval.mission_s256, spend, False, now
            )
        if ended is None:
            raise MissionTerminated("the mission has ended", status=409)
        return approval.mission_s256

    async def _record_federation(
        self, tenant: str, approval_id: str, outcome: Outcome
    ) -> bool:
        async with self.store.transaction() as tx:
            approval = await tx.select_approval(tenant, approval_id)
            federation = approval.federation if approval else None
            if (
                approval is None
                or federation is None
                or federation.settled
                or approval.status is not ApprovalStatus.APPROVED
            ):
                return False
            now = self.clock()
            status: ApprovalStatus = approval.status
            if outcome.step is Step.PENDING:
                if outcome.requirement == federation.requirement:
                    return approval.expires_at > now
                federation = federation.model_copy(
                    update={"requirement": outcome.requirement}
                )
            elif outcome.step is Step.ISSUED:
                refusal = await self._spend_granted(
                    tx, tenant, approval, outcome, now
                )
                if refusal is None:
                    federation = federation.model_copy(
                        update={
                            "auth_token": outcome.auth_token,
                            "auth_token_expires_at": outcome.auth_token_expires_at,
                        }
                    )
                else:
                    status, federation = (
                        ApprovalStatus.DENIED,
                        federation.model_copy(update={"refusal": refusal}),
                    )
            else:
                status, federation = (
                    ApprovalStatus.DENIED,
                    federation.model_copy(update={"refusal": outcome.refusal}),
                )
            changed = approval.model_copy(
                update={
                    "status": status,
                    "federation": federation,
                    "version": approval.version + 1,
                }
            )
            if approval.expires_at <= now or not await tx.transition_approval(
                tenant, approval, changed
            ):
                raise _Stale
        return outcome.step is Step.PENDING

    async def _spend_granted(
        self,
        tx: Store,
        tenant: str,
        approval: Approval,
        outcome: Outcome,
        now: int,
    ) -> Refusal | None:
        """Spend what the Access Server granted, which may be less than was asked."""
        mission_s256 = approval.mission_s256
        within_budget = bool(
            approval.federation and approval.federation.within_budget
        )
        if mission_s256 is None:
            return Refusal(
                status=404, error="mission_not_found", detail="no such mission"
            )
        mission = await tx.select_mission(tenant, mission_s256)
        granted = outcome.granted
        spend = (
            granted.amount
            if granted is not None
            and mission is not None
            and mission.budget is not None
            and mission.budget.same_scale(granted)
            else None
        )
        if await tx.update_spend(
            tenant,
            mission_s256,
            spend,
            within_budget and spend is not None,
            now,
        ):
            return None
        if (
            mission is None
            or mission.completed_at is not None
            or mission.expires_at <= now
        ):
            return Refusal(
                status=403,
                error="mission_terminated",
                detail="the mission has ended",
            )
        return Refusal(
            status=403,
            error="denied",
            detail="the mission's budget no longer covers this request; ask again",
        )

    # endregion
