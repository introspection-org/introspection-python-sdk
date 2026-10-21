"""The Person Server's side of four-party access (`#access-server-federation`).

A resource token whose `aud` is the resource's own Access Server is redeemed
there: the Person Server signs as itself (`#ps-to-as-token-request`), follows
the deferred loop (`#deferred-responses`), and checks the auth token before
the agent gets it (`#auth-token-delivery`).

The loop is steps a host can journal: `discover`, `request`, `record`, wait
`poll_delay`, `poll`, `record`, and so on; `run` is that loop in-process.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import http_sfv
import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from ..protocol import jwt
from ..protocol.errors import VerificationError
from ..protocol.keys import thumbprint
from ..protocol.models import Budget
from ..protocol.server import ACCESS_DWK
from .models import Approval, ApprovalStatus, Federation, Refusal
from .store import Store

if TYPE_CHECKING:
    from .server import PersonServer

SERVED = frozenset({"approval", "interaction"})
#: Requirements draft -11 defines that this Person Server does not serve.
NOT_SERVED = frozenset({"claims", "clarification"})
#: Seconds to wait before each retry of a request that could not connect.
TRANSPORT_RETRY_DELAYS = (1.0, 2.0, 4.0)
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
    location: str | None = None
    requirement: str | None = None
    retry_after: int | None = None
    refusal: Refusal | None = None


@dataclass(frozen=True)
class Metadata:
    issuer: str
    jwks_uri: str
    auth_token_endpoint: str


def refused(status: int, error: str, detail: str) -> Outcome:
    return Outcome(
        step=Step.REFUSED,
        refusal=Refusal(status=status, error=error, detail=detail),
    )


def unreachable(detail: str) -> Outcome:
    """`as_unreachable`: no verifiable answer from the Access Server."""
    return refused(502, "as_unreachable", detail)


def poll_delay(outcome: Outcome) -> int:
    """`Retry-After`, 5 seconds when absent; never a hot loop, never a stall."""
    if outcome.retry_after is None:
        return DEFAULT_DELAY
    return min(max(outcome.retry_after, MIN_DELAY), MAX_DELAY)


def _https(value: Any, endpoint: bool) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and not (endpoint and (parts.query or parts.fragment))
    )


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port


def _retry_after(response: httpx.Response) -> int | None:
    try:
        return max(int(response.headers.get("retry-after", "")), 0)
    except ValueError:
        return None


def _requirement(header: str) -> str | None:
    parsed = http_sfv.Dictionary()
    try:
        parsed.parse(header.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
    item = parsed.get("requirement")
    return str(item.value) if item is not None else None


def _scopes(value: Any) -> set[str]:
    return set(value.split()) if isinstance(value, str) else set()


class AccessServerClient:
    """Talks to the Access Server a verified resource token names, signed as the Person Server."""

    def __init__(self, ps: "PersonServer"):
        self._ps = ps

    async def discover(self, access_server: str) -> Metadata | Outcome:
        """`{aud}/.well-known/aauth-access.json`, whose `issuer` is the `aud`."""
        try:
            document = await self._ps.discovery.get_json(
                f"{access_server}/.well-known/{ACCESS_DWK}"
            )
        except VerificationError as exc:
            return unreachable(f"its metadata could not be read: {exc.detail}")
        if document.get("issuer") != access_server:
            return unreachable("its metadata names another issuer")
        if not _https(document.get("auth_token_endpoint"), True) or not _https(
            document.get("jwks_uri"), False
        ):
            return unreachable(
                "its metadata lacks an https auth_token_endpoint and jwks_uri"
            )
        return Metadata(
            access_server,
            str(document["jwks_uri"]),
            str(document["auth_token_endpoint"]),
        )

    async def request(
        self, federation: Federation, agent_jkt: str, metadata: Metadata
    ) -> Outcome:
        """The token request, with the budget the Person Server allows."""
        body = json.dumps(
            {
                "resource_token": federation.resource_token,
                "agent_token": federation.agent_token,
                "presented_token": federation.presented_token,
                **(
                    {"budget": federation.budget.model_dump()}
                    if federation.budget
                    else {}
                ),
            },
            separators=(",", ":"),
        ).encode()
        url = metadata.auth_token_endpoint
        headers = self._ps.identity.signed("POST", url, body, self._ps.clock())
        response = await self._ps.http.post(url, content=body, headers=headers)
        return await self._outcome(
            response, url, federation, agent_jkt, metadata
        )

    async def poll(
        self,
        location: str,
        federation: Federation,
        agent_jkt: str,
        metadata: Metadata,
    ) -> Outcome:
        headers = self._ps.identity.signed(
            "GET", location, None, self._ps.clock()
        )
        response = await self._ps.http.get(location, headers=headers)
        return await self._outcome(
            response, location, federation, agent_jkt, metadata
        )

    async def _outcome(  # noqa: PLR0911
        self,
        response: httpx.Response,
        requested: str,
        federation: Federation,
        agent_jkt: str,
        metadata: Metadata,
    ) -> Outcome:
        status = response.status_code
        if status == 200:
            try:
                auth_token = response.json().get("auth_token")
            except (ValueError, AttributeError):
                auth_token = None
            if not isinstance(auth_token, str):
                return unreachable("it answered 200 without an auth_token")
            return await self._delivered(
                auth_token, federation, agent_jkt, metadata
            )
        if status == 202:
            return self._waiting(response, requested)
        if status == 402:
            return refused(
                403,
                "denied",
                "the Access Server asks for payment, which this Person Server does not make",
            )
        if status in (429, 503) and requested != metadata.auth_token_endpoint:
            retry = _retry_after(response) or 0
            return Outcome(
                step=Step.PENDING,
                location=requested,
                requirement=federation.requirement or "requirement=approval",
                retry_after=retry + 5 if status == 429 else retry,
            )
        try:
            problem = response.json()
        except ValueError:
            problem = None
        error = problem.get("error") if isinstance(problem, dict) else None
        if 400 <= status < 500 and isinstance(error, str) and error:
            detail = (
                problem.get("detail") if isinstance(problem, dict) else None
            )
            return refused(
                status,
                error,
                f"the Access Server refused: {detail if isinstance(detail, str) else error}",
            )
        return unreachable(f"it answered {status}")

    @staticmethod
    def _waiting(response: httpx.Response, requested: str) -> Outcome:
        header = response.headers.get("aauth-requirement")
        requirement = _requirement(header) if header else "approval"
        if requirement is None:
            return unreachable("its AAuth-Requirement is malformed")
        if requirement in NOT_SERVED:
            return refused(
                403,
                "denied",
                f"the Access Server asks for requirement={requirement}, not served here",
            )
        location = response.headers.get("location")
        polled = urljoin(requested, location) if location else None
        if polled is None or _origin(polled) != _origin(requested):
            return unreachable("its pending Location is not on its own origin")
        return Outcome(
            step=Step.PENDING,
            location=polled,
            # An unrecognised requirement is polled through, and relayed as approval.
            requirement=header
            if header and requirement in SERVED
            else "requirement=approval",
            retry_after=_retry_after(response),
        )

    async def _delivered(
        self,
        auth_token: str,
        federation: Federation,
        agent_jkt: str,
        metadata: Metadata,
    ) -> Outcome:
        """`#auth-token-delivery`, and the budget granted no more than was sent."""
        rt = jwt.decode(federation.resource_token).claims
        presented = jwt.decode(federation.presented_token).claims
        try:
            keys = await self._ps.discovery.get_json(metadata.jwks_uri)
            claims = jwt.verify(
                auth_token, keys, jwt.AUTH_TOKEN, self._ps.clock()
            )
            granted = (
                Budget.model_validate(claims["budget"])
                if "budget" in claims
                else None
            )
        except (VerificationError, ValidationError) as exc:
            return unreachable(f"its auth token does not verify: {exc}")
        cnf = claims.get("cnf")
        jwk = cnf.get("jwk") if isinstance(cnf, dict) else None
        sent = federation.budget
        checks = {
            "dwk": claims.get("dwk") != ACCESS_DWK,
            "iss": claims.get("iss") != metadata.issuer,
            "aud": claims.get("aud") != rt.get("iss"),
            "cnf": not isinstance(jwk, dict) or _thumbprint(jwk) != agent_jkt,
            "sub": claims.get("sub") != rt.get("sub"),
            "ps": claims.get("ps") != self._ps.issuer,
            "mission_s256": claims.get("mission_s256")
            != rt.get("mission_s256"),
            "scope": not _scopes(claims.get("scope"))
            <= _scopes(rt.get("scope")),
            "exp": claims["exp"] > presented.get("exp", 0),
            "lifetime": claims["exp"] - claims["iat"]
            > jwt.MAX_TOKEN_LIFETIME_SECONDS,
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
        wrong = [name for name, failed in checks.items() if failed]
        if wrong:
            return unreachable(
                f"its auth token has the wrong {', '.join(wrong)}"
            )
        return Outcome(
            step=Step.ISSUED,
            auth_token=auth_token,
            auth_token_expires_at=int(claims["exp"]),
            granted=granted,
        )


def _thumbprint(jwk: dict[str, Any]) -> str | None:
    try:
        return thumbprint(jwk)
    except VerificationError:
        return None


async def due(
    ps: "PersonServer", tenant: str, approval_id: str
) -> tuple[Federation, str] | None:
    """The federation still to run for an approval, and the agent's key thumbprint."""
    approval = await ps.store.approval(tenant, approval_id)
    if (
        approval is None
        or approval.federation is None
        or approval.federation.settled
        or approval.status is not ApprovalStatus.APPROVED
    ):
        return None
    return approval.federation, approval.agent_jkt


async def record(
    ps: "PersonServer", tenant: str, approval_id: str, outcome: Outcome
) -> bool:
    """Record what the Access Server answered; whether to keep polling. The
    spend lands only when it issues, in the same transaction as its token."""
    try:
        return await _record(ps, tenant, approval_id, outcome)
    except _Stale:
        return False


async def _record(
    ps: "PersonServer", tenant: str, approval_id: str, outcome: Outcome
) -> bool:
    async with ps.store.transaction() as tx:
        approval = await tx.approval(tenant, approval_id)
        federation = approval.federation if approval else None
        if (
            approval is None
            or federation is None
            or federation.settled
            or approval.status is not ApprovalStatus.APPROVED
        ):
            return False
        now = ps.clock()
        status = approval.status
        if outcome.step is Step.PENDING:
            if outcome.requirement == federation.requirement:
                return approval.expires_at > now
            federation = federation.model_copy(
                update={"requirement": outcome.requirement}
            )
        elif outcome.step is Step.ISSUED:
            refusal = await _spend(tx, tenant, approval, outcome, now)
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


class _Stale(Exception):
    """Rolls a `record` back: the approval changed or lapsed meanwhile."""


async def _spend(
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
    mission = await tx.mission(tenant, mission_s256)
    granted = outcome.granted
    spend = (
        granted.amount
        if granted is not None
        and mission is not None
        and mission.budget is not None
        and mission.budget.same_scale(granted)
        else None
    )
    if await tx.spend(
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


async def run(
    ps: "PersonServer",
    tenant: str,
    approval_id: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Step | None:
    """Redeem an approved request at its Access Server, polling while it decides."""
    found = await due(ps, tenant, approval_id)
    if found is None:
        return None
    federation, agent_jkt = found
    client = AccessServerClient(ps)
    metadata = await client.discover(federation.access_server)

    async def attempt(call: Callable[[], Awaitable[Outcome]]) -> Outcome:
        """`call`, retried while the Access Server cannot be reached, then `as_unreachable`."""
        for delay in TRANSPORT_RETRY_DELAYS:
            try:
                return await call()
            except httpx.TransportError:
                await sleep(delay)
        try:
            return await call()
        except httpx.TransportError as exc:
            return unreachable(f"it could not be reached: {exc}")

    outcome = (
        metadata
        if isinstance(metadata, Outcome)
        else await attempt(
            partial(client.request, federation, agent_jkt, metadata)
        )
    )
    while True:
        waiting = await record(ps, tenant, approval_id, outcome)
        if (
            not waiting
            or outcome.location is None
            or isinstance(metadata, Outcome)
        ):
            return outcome.step
        await sleep(poll_delay(outcome))
        federation = federation.model_copy(
            update={"requirement": outcome.requirement}
        )
        outcome = await attempt(
            partial(
                client.poll, outcome.location, federation, agent_jkt, metadata
            )
        )
