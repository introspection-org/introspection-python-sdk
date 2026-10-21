"""Refusals, expiries and summaries, on both servers."""

from urllib.parse import urlsplit

import httpx2 as httpx
import pytest

from introspection_aauth.access_server import Verdict
from introspection_aauth.person_server import (
    Approval,
    ApprovalStatus,
    federation,
)
from introspection_aauth.person_server.models import (
    AuthTokenRequest,
    MissionProposal,
    PersonTokenRequest,
)
from introspection_aauth.protocol import AAuthError, SigningKey, s256
from introspection_aauth.protocol.httpsig import jwks_uri_key, sign
from introspection_aauth.protocol.jwt import RESOURCE_TOKEN, encode
from introspection_aauth.protocol.wire import (
    PersonTokenAnswer,
    R3Display,
    R3Proposal,
    TokenRequest,
)

from .test_federation import inline
from .world import AS, PS, RESOURCE, TENANT, World, body, problem, usd


def approval_id(response: httpx.Response) -> str:
    return urlsplit(response.headers["location"]).path.rsplit("/", 1)[1]


async def test_an_approval_nobody_answers_expires():
    world = World()
    world.ps._approval_ttl = 60
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(description="x", login_hint="sam"),
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
    _, person_token = world.resource_token(mission, 10)
    claims = world.resource_claims(mission, 10).model_copy(
        update={"iss": "https://elsewhere.example"}
    )
    forged = encode(claims, world.resource_key, RESOURCE_TOKEN)
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(resource_token=forged, presented_token=person_token),
    )
    assert refused.status_code == 403
    assert not any("elsewhere" in c for c in world.net.calls)


async def test_a_resource_token_not_matching_the_presented_token_is_refused():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    token, _ = world.resource_token(mission, 10)
    other = await world.call(
        "POST",
        f"{PS}/aauth/person-token",
        PersonTokenRequest(resource=RESOURCE),
    )
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=token,
            presented_token=body(other, PersonTokenAnswer).person_token,
        ),
    )
    assert refused.status_code == 400
    assert problem(refused).error == "invalid_resource_token"


async def test_an_expired_presented_token_is_never_federated():
    world = World()
    world.ps._token_ttl = 60
    mission = await world.approved_mission(budget=1_000)
    token, person_token = world.resource_token(mission, 10, aud=AS)
    world.now += 120
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(resource_token=token, presented_token=person_token),
    )
    assert problem(refused).error == "expired_presented_token"


async def test_an_access_server_that_cannot_be_reached_is_as_unreachable():
    world = World()
    inline(world)
    del world.net.apps[AS]
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 10, aud=AS))
    assert refused.status_code == 502
    assert problem(refused).error == "as_unreachable"
    assert await world.spent(mission.s256) == 0


async def test_an_access_server_asking_for_claims_is_refused():
    world = World()
    inline(world)
    app = world.net.apps[AS]

    class AsksForClaims(httpx.AsyncBaseTransport):
        async def handle_async_request(
            self, request: httpx.Request
        ) -> httpx.Response:
            if request.url.path == "/token":
                return httpx.Response(
                    202,
                    headers={
                        "AAuth-Requirement": "requirement=claims",
                        "Location": "/pending/1",
                    },
                )
            return await app.handle_async_request(request)

    world.net.apps[AS] = AsksForClaims()
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 10, aud=AS))
    assert refused.status_code == 403


async def test_a_busy_access_server_is_polled_again_later():
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant: str, approval: Approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    await world.ask(mission, 10, aud=AS)
    due = await world.ps.federation_due(TENANT, kicked[0])
    assert due is not None
    client = world.ps.access_server_client()
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    first = await client.request(due[0], due[1], metadata)
    app = world.net.apps[AS]

    class Busy(httpx.AsyncBaseTransport):
        async def handle_async_request(
            self, request: httpx.Request
        ) -> httpx.Response:
            if request.url.path.startswith("/pending"):
                return httpx.Response(429, headers={"Retry-After": "2"})
            return await app.handle_async_request(request)

    world.net.apps[AS] = Busy()
    assert first.location is not None
    busy = await client.poll(first.location, due[0], due[1], metadata)
    assert busy.step is federation.Step.PENDING and busy.poll_delay() == 7


async def test_the_access_server_refuses_what_it_does_not_decide():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    token, person_token = world.resource_token(mission, 10, aud=PS)
    content = TokenRequest(
        resource_token=token,
        agent_token=world.agent_token,
        presented_token=person_token,
    ).to_json()
    url = f"{AS}/token"
    unsigned = await world.http.post(url, content=content)
    assert unsigned.status_code == 401
    stranger = SigningKey.generate()
    headers = sign(
        stranger,
        jwks_uri_key(
            "https://stranger.example", "aauth-person.json", stranger.kid
        ),
        "POST",
        url,
        body=content,
        created=world.now,
    )
    refused = await world.http.post(url, content=content, headers=headers)
    assert refused.status_code == 401
    ps_signed = world.ps.identity.signed("POST", url, content, world.now)
    wrong_audience = await world.http.post(
        url, content=content, headers=ps_signed
    )
    assert wrong_audience.status_code == 400
    assert problem(wrong_audience).error == "invalid_resource_token"


async def test_an_interaction_is_relayed_and_a_decision_settles_once():
    world = World(
        policy=lambda request: Verdict.interaction(
            "https://as.booking.example/i", "ABCD"
        )
    )
    kicked: list[str] = []

    async def kick(tenant: str, approval: Approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 10, aud=AS)
    due = await world.ps.federation_due(TENANT, kicked[0])
    assert due is not None
    client = world.ps.access_server_client()
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    outcome = await client.request(due[0], due[1], metadata)
    await world.ps.record_federation(TENANT, kicked[0], outcome)
    relayed = await world.follow(asked)
    assert "requirement=interaction" in relayed.headers["aauth-requirement"]
    [pending] = list(world.access_store.requests.values())
    await world.access.decide(pending.id, False)
    with pytest.raises(AAuthError):
        await world.access.decide(pending.id, True)
    assert outcome.location is not None
    denied = await client.poll(outcome.location, due[0], due[1], metadata)
    assert denied.step is federation.Step.REFUSED
    await world.ps.record_federation(TENANT, kicked[0], denied)
    assert (await world.follow(asked)).status_code == 403


async def test_a_policy_may_not_grant_more_than_was_asked():
    world = World(policy=lambda request: Verdict.allow(scope="book cancel"))
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 10, aud=AS))
    assert refused.status_code == 502


async def test_a_calls_r3_proposal_is_read_into_its_approval():
    world = World()
    proposal = R3Proposal(
        display=R3Display(summary="Book QF1 for $600")
    ).to_json()
    r3_uri = f"{RESOURCE}/r3/1"

    world.net.documents[r3_uri] = proposal
    mission = await world.approved_mission(budget=1_000)
    _, person_token = world.resource_token(mission, 60_000)
    claims = world.resource_claims(mission, 60_000).model_copy(
        update={"r3_uri": r3_uri, "r3_s256": s256(proposal)}
    )
    with_proposal = encode(claims, world.resource_key, RESOURCE_TOKEN)
    over = await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=with_proposal, presented_token=person_token
        ),
    )
    described = await world.ps.describe(TENANT, approval_id(over))
    assert described is not None and described.summary == "Book QF1 for $600"


async def over_budget_with_proposal(
    world: World, proposal: bytes, r3_s256: str | None = None, aud: str = PS
) -> str:
    r3_uri = f"{RESOURCE}/r3/1"
    world.net.documents[r3_uri] = proposal
    mission = await world.approved_mission(budget=1_000)
    _, person_token = world.resource_token(mission, 60_000, aud)
    claims = world.resource_claims(mission, 60_000, aud).model_copy(
        update={"r3_uri": r3_uri, "r3_s256": r3_s256 or s256(proposal)}
    )
    over = await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=encode(claims, world.resource_key, RESOURCE_TOKEN),
            presented_token=person_token,
        ),
    )
    return approval_id(over)


SUMMARY = R3Proposal(display=R3Display(summary="Book QF1 for $600")).to_json()


async def test_a_summary_written_meanwhile_does_not_make_a_decision_stale():
    world = World()
    pending = await over_budget_with_proposal(world, SUMMARY)
    read = await world.ps_store.select_approval(TENANT, pending)
    assert read is not None
    await world.ps.describe(TENANT, pending)
    decided = read.model_copy(
        update={"status": ApprovalStatus.APPROVED, "version": read.version + 1}
    )
    assert await world.ps_store.transition_approval(TENANT, read, decided)
    stored = await world.ps_store.select_approval(TENANT, pending)
    assert stored is not None and stored.summary == "Book QF1 for $600"
    assert stored.status is ApprovalStatus.APPROVED


async def test_a_summary_written_meanwhile_does_not_drop_a_federated_token():
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant: str, approval: Approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    r3_uri = f"{RESOURCE}/r3/1"
    world.net.documents[r3_uri] = SUMMARY
    _, person_token = world.resource_token(mission, 10, AS)
    claims = world.resource_claims(mission, 10, AS).model_copy(
        update={"r3_uri": r3_uri, "r3_s256": s256(SUMMARY)}
    )
    await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=encode(claims, world.resource_key, RESOURCE_TOKEN),
            presented_token=person_token,
        ),
    )
    due = await world.ps.federation_due(TENANT, kicked[0])
    assert due is not None
    client = world.ps.access_server_client()
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    first = await client.request(due[0], due[1], metadata)
    assert await world.ps.record_federation(TENANT, kicked[0], first)
    [pending] = list(world.access_store.requests.values())
    await world.access.decide(pending.id, True)
    assert first.location is not None
    issued = await client.poll(first.location, due[0], due[1], metadata)
    await world.ps.describe(TENANT, kicked[0])
    assert not await world.ps.record_federation(TENANT, kicked[0], issued)
    stored = await world.ps_store.select_approval(TENANT, kicked[0])
    assert stored is not None and stored.federation is not None
    assert stored.federation.auth_token is not None
    assert stored.summary == "Book QF1 for $600"


@pytest.mark.parametrize(
    ("proposal", "r3_s256"),
    [(b"not json", None), (SUMMARY, "the wrong hash")],
)
async def test_an_unreadable_proposal_leaves_the_approval_without_a_summary(
    proposal: bytes, r3_s256: str | None
):
    world = World()
    pending = await over_budget_with_proposal(world, proposal, r3_s256)
    described = await world.ps.describe(TENANT, pending)
    assert described is not None and described.summary is None
