"""An AAuth Person Server (draft-hardt-oauth-aauth-protocol -11): missions,
person and auth tokens, budgets, approvals, and federation with a resource's
own Access Server. Framework-free: each method takes a `SignedRequest` and
returns an `Answer`, or raises `AAuthError`."""

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Unpack
from urllib.parse import quote

import httpx2 as httpx

from ..protocol import jwt
from ..protocol.errors import AAuthError, Answer, VerificationError
from ..protocol.httpsig import SignedRequest
from ..protocol.keys import SigningKey, b64url, s256
from ..protocol.models import Agent, Budget
from ..protocol.server import (
    PERSON_DWK,
    RESOURCE_DWK,
    Server,
    ServerOptions,
    https_origin,
    parse,
    pending,
    verify_agent,
)
from .federation import run
from .models import (
    Approval,
    ApprovalKind,
    ApprovalStatus,
    AuthTokenRequest,
    Federation,
    LogEntry,
    Mission,
    MissionAction,
    MissionProposal,
    PersonTokenRequest,
)
from .store import AnyoneDirectory, Directory, Store

logger = logging.getLogger(__name__)

Hook = Callable[[str, Approval], Awaitable[None]]


def _budget(claims: dict[str, Any]) -> Budget | None:
    try:
        return (
            Budget.model_validate(claims["budget"])
            if claims.get("budget") is not None
            else None
        )
    except ValueError:
        raise AAuthError(
            400, "invalid_resource_token", "budget is not a budget object"
        ) from None


def _fits(mission: Mission, budget: Budget | None) -> bool:
    """Whether a request is within what is left of its mission's budget."""
    return budget is None or (
        mission.budget is not None
        and mission.budget.same_scale(budget)
        and mission.budget.amount - mission.spent >= budget.amount
    )


class PersonServer(Server):
    """Speaks for the people its `Directory` names, keeping its state in a `Store`.

    `subject_secret` keys each person's directed `sub` and is kept apart from
    the signing key, so rotating the key changes no one's identifier.
    `on_approval` is told of each approval a person must decide; `on_federate`
    of each approved request its resource's Access Server must decide, which
    the host runs with `federation.run` or journals step by step. Unset, it is
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
        self._token_ttl, self._mission_ttl = token_ttl, mission_ttl
        self._approval_ttl = approval_ttl
        self._on_approval, self._on_federate = on_approval, on_federate
        self._running: set[asyncio.Task[Any]] = set()

    # region documents
    def metadata(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            **({"name": self.name} if self.name else {}),
            "jwks_uri": f"{self.issuer}/.well-known/aauth-person-jwks.json",
            "person_token_endpoint": f"{self.endpoint_base}/person-token",
            "auth_token_endpoint": f"{self.endpoint_base}/token",
            "mission_endpoint": f"{self.endpoint_base}/mission",
            "claims_supported": ["sub", "tenant"],
        }

    def pending_url(self, tenant: str, approval_id: str) -> str:
        return f"{self.endpoint_base}/pending/{quote(tenant, safe='')}/{approval_id}"

    # endregion

    # region people and tokens
    def _tenant(self, named: str | None) -> str:
        tenant = named or self._default_tenant
        if not tenant:
            raise AAuthError(400, "invalid_request", "name the tenant")
        return tenant

    async def _agent(self, request: SignedRequest) -> Agent:
        agent = await verify_agent(
            request, self.discovery, self._providers, self.clock()
        )
        if (
            agent.person_server is not None
            and agent.person_server != self.issuer
        ):
            raise AAuthError(
                403, "invalid_request", "this agent's Person Server is another"
            )
        return agent

    async def _person(
        self, tenant: str, agent: Agent, login_hint: str | None
    ) -> str:
        """Who the agent acts for. A key is bound to the first person it names."""
        if login_hint is None:
            bound = await self.store.binding(tenant, agent.jkt)
            if bound is None:
                raise AAuthError(
                    400, "invalid_request", "name the person: login_hint"
                )
            return bound
        person = self.directory.person(login_hint, tenant)
        if person is None:
            raise AAuthError(
                403,
                "access_denied",
                "this Person Server does not speak for them",
            )
        if await self.store.bind(tenant, agent.jkt, person) != person:
            raise AAuthError(
                403, "invalid_request", "this agent acts for another person"
            )
        return person

    def directed_subject(self, person: str, audience: str) -> str:
        """The person's identifier at one audience; no two audiences can correlate it."""
        message = f"{person}\n{audience}".encode()
        return b64url(
            hmac.new(self._subject_secret, message, hashlib.sha256).digest()
        )

    def _issue(
        self, typ: str, claims: dict[str, Any], expires_at: int, tenant: str
    ) -> tuple[str, int]:
        now = self.clock()
        token = self.identity.token(
            {
                "iss": self.issuer,
                "dwk": PERSON_DWK,
                "tenant": tenant,
                "jti": self.new_id(),
                "iat": now,
                "exp": expires_at,
                **claims,
            },
            typ,
        )
        return token, expires_at - now

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
    ) -> dict[str, Any]:
        token, expires_in = self._issue(
            jwt.PERSON_TOKEN,
            {
                "aud": resource,
                "sub": self.directed_subject(person, resource),
                "cnf": {"jwk": agent.jwk},
                **({"mission_s256": mission.s256} if mission else {}),
            },
            self._expiry(agent, mission.expires_at if mission else None),
            tenant,
        )
        return {"person_token": token, "expires_in": expires_in}

    def _auth_token(
        self,
        tenant: str,
        agent: Agent,
        grant: dict[str, Any],
        mission: Mission,
    ) -> dict[str, Any]:
        token, expires_in = self._issue(
            jwt.AUTH_TOKEN,
            {
                "ps": self.issuer,
                "cnf": {"jwk": agent.jwk},
                "mission_s256": mission.s256,
                **grant,
            },
            self._expiry(agent, mission.expires_at),
            tenant,
        )
        return {"auth_token": token, "expires_in": expires_in}

    # endregion

    # region missions
    def _live(self, mission: Mission | None, agent_id: str) -> Mission:
        """The mission, if it is this agent's and live; the same 404 otherwise."""
        if mission is None or mission.agent_id != agent_id:
            raise AAuthError(404, "mission_not_found", "no such mission")
        if mission.completed_at is not None:
            raise AAuthError(403, "mission_terminated", "mission completed")
        if mission.expires_at <= self.clock():
            raise AAuthError(403, "mission_terminated", "mission expired")
        return mission

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
            grant={"resources": resources},
        )
        await self.store.put_approval(tenant, approval)
        return await self._ask(tenant, approval)

    async def mission_action(
        self, request: SignedRequest, mission_s256: str
    ) -> Answer:
        """`POST /mission/{s256}`: log an update, or propose the mission complete."""
        agent = await self._agent(request)
        action = parse(MissionAction, request.body)
        tenant = self._tenant(action.tenant)
        mission = self._live(
            await self.store.mission(tenant, mission_s256), agent.id
        )
        if action.action == "update":
            entry = action.description or ""
            if not await self.store.log_mission(
                tenant,
                mission.s256,
                LogEntry(at=self.clock(), entry=entry),
                self.clock(),
            ):
                raise AAuthError(
                    403, "mission_terminated", "the mission has ended"
                )
            return Answer(200, {"s256": s256(entry.encode())})
        if action.action != "completion":
            raise AAuthError(
                400, "invalid_request", "action is update or completion"
            )
        approval = self._new_approval(
            ApprovalKind.COMPLETION,
            agent,
            mission.person,
            action.summary or "The agent says the mission is done",
            mission_s256=mission.s256,
        )
        await self.store.put_approval(tenant, approval)
        return await self._ask(tenant, approval)

    async def person_token(self, request: SignedRequest) -> Answer:
        """`POST /person-token`: who the agent acts for, at one resource."""
        agent = await self._agent(request)
        body = parse(PersonTokenRequest, request.body)
        tenant = self._tenant(body.tenant)
        resource = body.resource.rstrip("/")
        if not https_origin(resource):
            raise AAuthError(
                400, "invalid_request", "resource is an https origin"
            )
        person = await self._person(tenant, agent, body.login_hint)
        mission = None
        if body.mission_s256 is not None:
            mission = self._live(
                await self.store.mission(tenant, body.mission_s256), agent.id
            )
            if mission.person != person:
                raise AAuthError(404, "mission_not_found", "no such mission")
        return Answer(
            200, self._person_token(tenant, agent, person, resource, mission)
        )

    # endregion

    # region auth tokens
    def _presented(self, token: str) -> dict[str, Any]:
        """The presented person token; an expired one is refused before anything is federated."""
        try:
            return self.identity.verify_own(
                token, jwt.PERSON_TOKEN, self.clock()
            )
        except VerificationError as exc:
            code = (
                "expired_presented_token"
                if exc.code == "expired_jwt"
                else "invalid_presented_token"
            )
            raise AAuthError(
                400, code, "not a live token this Person Server issued"
            ) from None

    async def _resource_token(
        self, token: str, tenant: str, agent: Agent
    ) -> tuple[dict[str, Any], Mission]:
        """The resource token, verified against its resource's keys, and the
        live mission it falls under; only a mission's resources are fetched."""
        try:
            decoded = jwt.decode(token)
        except VerificationError:
            raise AAuthError(
                400, "invalid_resource_token", "not a JWT"
            ) from None
        unverified = decoded.claims
        if (
            decoded.header.get("typ") != jwt.RESOURCE_TOKEN
            or unverified.get("dwk") != RESOURCE_DWK
        ):
            raise AAuthError(
                400, "invalid_resource_token", "not a resource token"
            )
        if unverified.get("tenant") != tenant:
            raise AAuthError(
                400, "invalid_resource_token", "tenant does not match"
            )
        if not isinstance(unverified.get("mission_s256"), str):
            raise AAuthError(
                403,
                "access_denied",
                "an auth token is issued only within a mission",
            )
        mission = self._live(
            await self.store.mission(tenant, unverified["mission_s256"]),
            agent.id,
        )
        resource = str(unverified.get("iss", "")).rstrip("/")
        if resource not in mission.resources:
            raise AAuthError(
                403,
                "access_denied",
                "this mission does not cover that resource",
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
            raise AAuthError(
                400, "invalid_resource_token", f"does not verify: {exc.detail}"
            ) from None
        if str(rt.get("ps", "")).rstrip("/") != self.issuer:
            raise AAuthError(
                400, "invalid_resource_token", "not for this Person Server"
            )
        if rt.get("agent_jkt") != agent.jkt:
            raise AAuthError(
                400, "invalid_resource_token", "agent_jkt is not the signer"
            )
        return rt, mission

    def _access_server(self, rt: dict[str, Any]) -> str | None:
        """The resource's own Access Server, when `aud` is not this Person Server."""
        audience = rt.get("aud")
        if audience == self.issuer:
            return None
        if not https_origin(audience):
            raise AAuthError(
                400,
                "invalid_resource_token",
                "aud is neither this Person Server nor an Access Server",
            )
        return str(audience).rstrip("/")

    async def auth_token(self, request: SignedRequest) -> Answer:
        """`POST /token`: a call to a resource, weighed against the mission's budget."""
        agent = await self._agent(request)
        body = parse(AuthTokenRequest, request.body)
        tenant = self._tenant(body.tenant)
        presented = self._presented(body.presented_token)
        if presented.get("tenant") != tenant:
            raise AAuthError(
                400, "invalid_resource_token", "tenant does not match"
            )
        rt, mission = await self._resource_token(
            body.resource_token, tenant, agent
        )
        resource = str(rt["iss"]).rstrip("/")
        if (
            presented.get("jti") != rt.get("presented_jti")
            or presented.get("sub") != rt.get("sub")
            or presented.get("mission_s256") != rt.get("mission_s256")
            or presented.get("aud") != resource
        ):
            raise AAuthError(
                400,
                "invalid_resource_token",
                "does not match the presented token",
            )
        budget = _budget(rt)
        grant = {
            "aud": resource,
            "sub": rt["sub"],
            **{k: rt[k] for k in ("scope", "r3_uri", "r3_s256") if k in rt},
            **({"budget": budget.model_dump()} if budget else {}),
        }
        access_server = self._access_server(rt)
        if access_server is not None:
            if (
                body.upstream_token is not None
                or body.subagent_token is not None
            ):
                raise AAuthError(
                    400,
                    "invalid_request",
                    "call chaining and sub-agents are not federated here",
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
            spent = await self.store.spend(
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
            str(rt.get("scope") or "a request"),
            mission_s256=mission.s256,
            resource=resource,
            budget=budget,
            grant=grant,
        )
        await self.store.put_approval(tenant, approval)
        return await self._ask(tenant, approval)

    async def _federated(
        self,
        tenant: str,
        agent: Agent,
        mission: Mission,
        grant: dict[str, Any],
        federation: Federation,
    ) -> Answer:
        """The mission and budget are weighed first, as for any resource: a
        request they cover is approved here and redeemed at the Access Server;
        one over what is left goes to a person first."""
        approval = self._new_approval(
            ApprovalKind.AUTH_TOKEN,
            agent,
            mission.person,
            str(grant.get("scope") or "a request"),
            mission_s256=mission.s256,
            resource=grant["aud"],
            budget=federation.budget,
            grant=grant,
            federation=federation,
        )
        if not federation.within_budget:
            await self.store.put_approval(tenant, approval)
            return await self._ask(tenant, approval)
        approval = approval.model_copy(
            update={
                "status": ApprovalStatus.APPROVED,
                "decided_at": self.clock(),
            }
        )
        await self.store.put_approval(tenant, approval)
        await self.decided(tenant, approval)
        return pending(self.pending_url(tenant, approval.id), self.retry_after)

    # endregion

    # region approvals
    def _new_approval(
        self,
        kind: ApprovalKind,
        agent: Agent,
        person: str,
        description: str,
        **fields: Any,
    ) -> Approval:
        now = self.clock()
        return Approval(
            id=self.new_id(),
            kind=kind,
            agent_id=agent.id,
            agent_jkt=agent.jkt,
            agent_jwk=agent.jwk,
            person=person,
            description=description,
            expires_at=now + self._approval_ttl,
            created_at=now,
            **fields,
        )

    async def _ask(self, tenant: str, approval: Approval) -> Answer:
        if self._on_approval is not None:
            await self._on_approval(tenant, approval)
        return pending(self.pending_url(tenant, approval.id), self.retry_after)

    async def poll(
        self, request: SignedRequest, tenant: str, approval_id: str
    ) -> Answer:
        """`GET /pending/{tenant}/{id}`: only the key that asked may read it."""
        agent = await self._agent(request)
        approval = await self.store.approval(tenant, approval_id)
        if approval is None or approval.agent_jkt != agent.jkt:
            raise AAuthError(404, "not_found", "no such pending request")
        mission = (
            await self.store.mission(tenant, approval.mission_s256)
            if approval.mission_s256
            else None
        )
        federation = approval.federation
        if approval.status is ApprovalStatus.DENIED:
            refusal = federation.refusal if federation else None
            if refusal is not None:
                raise AAuthError(refusal.status, refusal.error, refusal.detail)
            raise AAuthError(403, "denied", "the approver declined")
        if approval.status is ApprovalStatus.PENDING:
            if approval.expires_at <= self.clock():
                raise AAuthError(408, "expired", "nobody answered in time")
            return pending(
                self.pending_url(tenant, approval.id), self.retry_after
            )
        if federation is not None:
            return await self._collect(
                tenant, agent, approval, federation, mission
            )
        if approval.kind is ApprovalKind.COMPLETION:
            return Answer(200, {})
        if mission is None:
            raise AAuthError(404, "mission_not_found", "no such mission")
        if approval.kind is ApprovalKind.MISSION:
            person_tokens = {
                r: self._person_token(
                    tenant, agent, mission.person, r, mission
                )["person_token"]
                for r in mission.resources
            }
            return Answer(
                200,
                {
                    "s256": mission.s256,
                    "mission": b64url(mission.mission.encode()),
                    "person_tokens": person_tokens,
                },
            )
        self._live(mission, agent.id)
        return Answer(
            200, self._auth_token(tenant, agent, approval.grant, mission)
        )

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
            raise AAuthError(
                410,
                "invalid_code",
                "this request's auth token was already collected",
            )
        if federation.auth_token is None:
            if approval.expires_at <= now:
                raise AAuthError(
                    408, "expired", "the Access Server did not answer in time"
                )
            return pending(
                self.pending_url(tenant, approval.id),
                self.retry_after,
                federation.requirement,
            )
        self._live(mission, agent.id)
        expires_in = (federation.auth_token_expires_at or 0) - now
        if expires_in <= 0:
            raise AAuthError(
                408,
                "expired",
                "the auth token expired before it was collected",
            )
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
            raise AAuthError(
                410,
                "invalid_code",
                "this request's auth token was already collected",
            )
        return Answer(
            200,
            {"auth_token": federation.auth_token, "expires_in": expires_in},
        )

    async def decide(
        self,
        tenant: str,
        approval_id: str,
        status: ApprovalStatus,
        *,
        decided_by: str,
        budget: Budget | None = None,
    ) -> Approval | None:
        """Record a person's answer, and do what was asked: create the mission,
        spend the call, or complete the mission. None if there is no such approval."""
        if status is ApprovalStatus.PENDING:
            raise AAuthError(
                422, "invalid_request", "status is approved or denied"
            )
        async with self.store.transaction():
            approval = await self.store.approval(tenant, approval_id)
            if approval is None:
                return None
            if (
                approval.kind is not ApprovalKind.MISSION
                and budget is not None
            ):
                raise AAuthError(
                    422, "invalid_request", "only a mission takes a budget"
                )
            if (
                approval.kind is ApprovalKind.COMPLETION
                and decided_by != approval.person
            ):
                raise AAuthError(
                    403,
                    "access_denied",
                    "a completion is accepted by the person the mission is for",
                )
            now = self.clock()
            if (
                approval.status is not ApprovalStatus.PENDING
                or approval.expires_at <= now
            ):
                raise AAuthError(
                    409,
                    "invalid_request",
                    "this approval is already decided or has expired",
                )
            mission_s256 = approval.mission_s256
            if status is ApprovalStatus.APPROVED:
                mission_s256 = await self._carry_out(
                    tenant, approval, budget, now
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
            if not await self.store.transition_approval(
                tenant, approval, decided
            ):
                raise AAuthError(
                    409,
                    "invalid_request",
                    "this approval is already decided or has expired",
                )
        await self.decided(tenant, decided)
        return decided

    async def _carry_out(
        self, tenant: str, approval: Approval, budget: Budget | None, now: int
    ) -> str | None:
        if approval.kind is ApprovalKind.MISSION:
            expires_at = now + self._mission_ttl
            resources = list(approval.grant.get("resources", []))
            # The approval and the person make the blob, and so its `s256`, the
            # mission's own: two alike approvals in one second must not share it.
            blob = json.dumps(
                {
                    "agent": approval.agent_id,
                    "approval": approval.id,
                    "person": approval.person,
                    "approved_at": datetime.fromtimestamp(
                        now, UTC
                    ).isoformat(),
                    "expires_at": datetime.fromtimestamp(
                        expires_at, UTC
                    ).isoformat(),
                    "description": approval.description,
                    "approved_resources": resources,
                    **({"budget": budget.model_dump()} if budget else {}),
                },
                separators=(",", ":"),
            )
            mission = Mission(
                s256=s256(blob.encode()),
                mission=blob,
                agent_id=approval.agent_id,
                person=approval.person,
                resources=resources,
                budget=budget,
                expires_at=expires_at,
            )
            if not await self.store.insert_mission(tenant, mission):
                raise AAuthError(
                    409,
                    "invalid_request",
                    "a mission with this hash exists already",
                )
            return mission.s256
        if approval.mission_s256 is None:
            return None
        current = await self.store.mission(tenant, approval.mission_s256)
        if approval.kind is ApprovalKind.COMPLETION:
            ended = await self.store.end_mission(
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
            ended = await self.store.spend(
                tenant, approval.mission_s256, spend, False, now
            )
        if ended is None:
            raise AAuthError(
                409, "mission_terminated", "the mission has ended"
            )
        return approval.mission_s256

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
        task = asyncio.create_task(run(self, tenant, approval.id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def describe(self, tenant: str, approval_id: str) -> Approval | None:
        """Read a call's R3 proposal into its approval's `summary`, for whoever decides."""
        approval = await self.store.approval(tenant, approval_id)
        if approval is None or not isinstance(
            approval.grant.get("r3_uri"), str
        ):
            return approval
        proposal = await self.identity.read_proposal(
            self.http,
            approval.grant["r3_uri"],
            str(approval.grant.get("r3_s256")),
            self.clock(),
        )
        display = proposal.get("display")
        summary = display.get("summary") if isinstance(display, dict) else None
        if not summary:
            return approval
        changed = approval.model_copy(
            update={
                "summary": str(summary)[:2_000],
                "version": approval.version + 1,
            }
        )
        return (
            changed
            if await self.store.transition_approval(tenant, approval, changed)
            else approval
        )

    # endregion
