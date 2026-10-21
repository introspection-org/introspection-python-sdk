"""Refusals, expiries and summaries, on both servers."""

import json
from urllib.parse import urlsplit

import httpx2 as httpx
import pytest

from introspection_aauth.access_server import Verdict
from introspection_aauth.person_server import ApprovalStatus, federation
from introspection_aauth.protocol import AAuthError, SigningKey, s256
from introspection_aauth.protocol.httpsig import jwks_uri_key, sign
from introspection_aauth.protocol.jwt import RESOURCE_TOKEN, decode, encode

from .test_federation import inline
from .world import AS, PS, RESOURCE, TENANT, World, usd


def approval_id(response) -> str:
    return urlsplit(response.headers["location"]).path.rsplit("/", 1)[1]


async def test_an_approval_nobody_answers_expires():
    world = World()
    world.ps._approval_ttl = 60
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        {"description": "x", "login_hint": "sam"},
    )
    world.now += 120
    expired = await world.follow(proposed)
    assert expired.status_code == 408
    with pytest.raises(AAuthError) as late:
        await world.ps.decide(
            TENANT,
            approval_id(proposed),
            ApprovalStatus.APPROVED,
            decided_by="dana",
        )
    assert late.value.status == 409


async def test_a_decision_is_made_once_and_only_a_mission_takes_a_budget():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    over = await world.ask(mission, 5_000)
    with pytest.raises(AAuthError) as budgeted:
        await world.ps.decide(
            TENANT,
            approval_id(over),
            ApprovalStatus.APPROVED,
            decided_by="dana",
            budget=usd(1),
        )
    assert budgeted.value.status == 422
    await world.ps.decide(
        TENANT, approval_id(over), ApprovalStatus.DENIED, decided_by="dana"
    )
    with pytest.raises(AAuthError) as twice:
        await world.ps.decide(
            TENANT,
            approval_id(over),
            ApprovalStatus.APPROVED,
            decided_by="dana",
        )
    assert twice.value.status == 409
    assert (
        await world.ps.decide(
            TENANT, "nope", ApprovalStatus.DENIED, decided_by="d"
        )
        is None
    )


async def test_a_resource_the_mission_does_not_cover_is_refused_before_its_keys_are_fetched():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    token, person_token = world.resource_token(mission, 10)
    claims = decode(token).claims | {"iss": "https://elsewhere.example"}
    forged = encode(claims, world.resource_key, RESOURCE_TOKEN)
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        {"resource_token": forged, "presented_token": person_token},
    )
    assert refused.status_code == 403
    assert not any("elsewhere" in c for c in world.net.calls)


async def test_a_resource_token_not_matching_the_presented_token_is_refused():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    token, _ = world.resource_token(mission, 10)
    other = await world.call(
        "POST", f"{PS}/aauth/person-token", {"resource": RESOURCE}
    )
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        {
            "resource_token": token,
            "presented_token": other.json()["person_token"],
        },
    )
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_resource_token"


async def test_an_expired_presented_token_is_never_federated():
    world = World()
    world.ps._token_ttl = 60
    mission = await world.approved_mission(budget=1_000)
    token, person_token = world.resource_token(mission, 10, aud=AS)
    world.now += 120
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        {"resource_token": token, "presented_token": person_token},
    )
    assert refused.json()["error"] == "expired_presented_token"


async def test_an_access_server_that_cannot_be_reached_is_as_unreachable():
    world = World()
    inline(world)
    del world.net.apps[AS]
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 10, aud=AS))
    assert refused.status_code == 502
    assert refused.json()["error"] == "as_unreachable"
    assert await world.spent(mission["s256"]) == 0


async def test_an_access_server_asking_for_claims_is_refused():
    world = World()
    inline(world)
    app = world.net.apps[AS]

    class AsksForClaims(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == "/token":
                return httpx.Response(
                    202,
                    headers={
                        "AAuth-Requirement": "requirement=claims",
                        "Location": "/pending/1",
                    },
                )
            return await app.handle_async_request(request)

    world.net.apps[AS] = AsksForClaims()  # type: ignore[assignment]
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 10, aud=AS))
    assert refused.status_code == 403


async def test_a_busy_access_server_is_polled_again_later():
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant, approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    await world.ask(mission, 10, aud=AS)
    due = await federation.due(world.ps, TENANT, kicked[0])
    assert due is not None
    client = federation.AccessServerClient(world.ps)
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    first = await client.request(due[0], due[1], metadata)
    app = world.net.apps[AS]

    class Busy(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path.startswith("/pending"):
                return httpx.Response(429, headers={"Retry-After": "2"})
            return await app.handle_async_request(request)

    world.net.apps[AS] = Busy()  # type: ignore[assignment]
    assert first.location is not None
    busy = await client.poll(first.location, due[0], due[1], metadata)
    assert (
        busy.step is federation.Step.PENDING
        and federation.poll_delay(busy) == 7
    )


async def test_the_access_server_refuses_what_it_does_not_decide():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    token, person_token = world.resource_token(mission, 10, aud=PS)
    body = json.dumps(
        {
            "resource_token": token,
            "agent_token": world.agent_token,
            "presented_token": person_token,
        }
    ).encode()
    url = f"{AS}/token"
    unsigned = await world.http.post(url, content=body)
    assert unsigned.status_code == 401
    stranger = SigningKey.generate()
    headers = sign(
        stranger,
        jwks_uri_key(
            "https://stranger.example", "aauth-person.json", stranger.kid
        ),
        "POST",
        url,
        body=body,
        created=world.now,
    )
    refused = await world.http.post(url, content=body, headers=headers)
    assert refused.status_code == 401
    ps_signed = world.ps.identity.signed("POST", url, body, world.now)
    wrong_audience = await world.http.post(
        url, content=body, headers=ps_signed
    )
    assert wrong_audience.status_code == 400
    assert wrong_audience.json()["error"] == "invalid_resource_token"


async def test_an_interaction_is_relayed_and_a_decision_settles_once():
    world = World(
        policy=lambda request: Verdict.interaction(
            "https://as.booking.example/i", "ABCD"
        )
    )
    kicked: list[str] = []

    async def kick(tenant, approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 10, aud=AS)
    due = await federation.due(world.ps, TENANT, kicked[0])
    assert due is not None
    client = federation.AccessServerClient(world.ps)
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    outcome = await client.request(due[0], due[1], metadata)
    await federation.record(world.ps, TENANT, kicked[0], outcome)
    relayed = await world.follow(asked)
    assert "requirement=interaction" in relayed.headers["aauth-requirement"]
    [pending] = list(world.access_store.requests.values())
    await world.access.decide(pending.id, False)
    with pytest.raises(AAuthError):
        await world.access.decide(pending.id, True)
    assert outcome.location is not None
    denied = await client.poll(outcome.location, due[0], due[1], metadata)
    assert denied.step is federation.Step.REFUSED
    await federation.record(world.ps, TENANT, kicked[0], denied)
    assert (await world.follow(asked)).status_code == 403


async def test_a_policy_may_not_grant_more_than_was_asked():
    world = World(policy=lambda request: Verdict.allow(scope="book cancel"))
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 10, aud=AS))
    assert refused.status_code == 502


async def test_a_calls_r3_proposal_is_read_into_its_approval():
    world = World()
    proposal = json.dumps(
        {"display": {"summary": "Book QF1 for $600"}}
    ).encode()
    r3_uri = f"{RESOURCE}/r3/1"

    world.net.documents[r3_uri] = proposal
    mission = await world.approved_mission(budget=1_000)
    token, person_token = world.resource_token(mission, 60_000)
    claims = decode(token).claims | {
        "r3_uri": r3_uri,
        "r3_s256": s256(proposal),
    }
    with_proposal = encode(claims, world.resource_key, RESOURCE_TOKEN)
    over = await world.call(
        "POST",
        f"{PS}/aauth/token",
        {"resource_token": with_proposal, "presented_token": person_token},
    )
    described = await world.ps.describe(TENANT, approval_id(over))
    assert described is not None and described.summary == "Book QF1 for $600"
