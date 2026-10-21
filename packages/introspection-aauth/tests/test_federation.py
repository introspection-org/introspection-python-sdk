"""Four-party (`#access-server-federation`): the Person Server weighs the
call against the mission, then redeems it at the resource's Access Server."""

from urllib.parse import urlsplit

import httpx2 as httpx

from introspection_aauth.access_server import Verdict
from introspection_aauth.person_server import (
    Approval,
    ApprovalStatus,
    Step,
)
from introspection_aauth.person_server.models import AuthTokenRequest
from introspection_aauth.protocol.claims import AuthTokenClaims
from introspection_aauth.protocol.keys import Jwks
from introspection_aauth.protocol.wire import (
    AccessServerMetadata,
    AuthTokenAnswer,
)

from .world import (
    AS,
    PS,
    RESOURCE,
    TENANT,
    World,
    body,
    problem,
    read,
    usd,
)


def auth_token(response: httpx.Response) -> AuthTokenClaims:
    return read(body(response, AuthTokenAnswer).auth_token, AuthTokenClaims)


def inline(world: World) -> list[str]:
    """Run each federation to its end before the agent's request is answered."""
    ran: list[str] = []

    async def run(tenant: str, approval: Approval) -> None:
        ran.append(approval.id)

        async def no_wait(_: float) -> None:
            return None

        await world.ps.federate(tenant, approval.id, sleep=no_wait)

    world.ps._on_federate = run
    return ran


async def test_the_access_server_publishes_its_metadata():
    world = World()
    metadata = body(
        await world.http.get(f"{AS}/.well-known/aauth-access.json"),
        AccessServerMetadata,
    )
    assert metadata.auth_token_endpoint == f"{AS}/token"
    keys = body(await world.http.get(metadata.jwks_uri), Jwks)
    assert keys == world.access.jwks()


async def test_an_allowed_call_is_issued_by_the_access_server_and_collected_once():
    world = World()
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 60_000, aud=AS)
    issued = await world.follow(asked)
    assert issued.status_code == 200, issued.text
    claims = auth_token(issued)
    assert claims.iss == AS and claims.aud == RESOURCE and claims.ps == PS
    assert claims.cnf.jwk == world.agent_key.public_jwk
    assert await world.spent(mission.s256) == 60_000
    again = await world.follow(asked)
    assert again.status_code == 410
    assert problem(again).error == "invalid_code"


async def test_a_refusal_is_relayed_and_nothing_is_spent():
    world = World(
        policy=lambda request: Verdict.deny("no Flight Sector account")
    )
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 60_000, aud=AS))
    assert refused.status_code == 403
    assert problem(refused).error == "denied"
    assert "no Flight Sector account" in (problem(refused).detail or "")
    assert await world.spent(mission.s256) == 0


async def test_a_smaller_grant_is_all_that_is_spent():
    world = World(policy=lambda request: Verdict.allow(budget=usd(40_000)))
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    issued = await world.follow(await world.ask(mission, 60_000, aud=AS))
    assert issued.status_code == 200, issued.text
    assert auth_token(issued).budget == usd(40_000)
    assert await world.spent(mission.s256) == 40_000


async def test_the_access_servers_wait_is_journaled_step_by_step():
    """What a durable host does: each step is one call it can record."""
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant: str, approval: Approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 60_000, aud=AS)
    approval_id = kicked[0]

    due = await world.ps.federation_due(TENANT, approval_id)
    assert due is not None
    fed, jkt = due
    client = world.ps.access_server_client()
    metadata = await client.discover(fed.access_server)
    assert isinstance(metadata, AccessServerMetadata)
    outcome = await client.request(fed, jkt, metadata)
    assert outcome.step is Step.PENDING
    assert await world.ps.record_federation(TENANT, approval_id, outcome)
    waiting = await world.follow(asked)
    assert waiting.status_code == 202
    assert waiting.headers["aauth-requirement"] == "requirement=approval"

    [pending] = list(world.access_store.requests.values())
    assert pending.request.budget == usd(60_000)
    await world.access.decide(pending.id, True, decided_by="flight-sector")
    assert outcome.location is not None
    outcome = await client.poll(outcome.location, fed, jkt, metadata)
    assert outcome.step is Step.ISSUED
    assert not await world.ps.record_federation(TENANT, approval_id, outcome)
    assert (await world.follow(asked)).status_code == 200
    assert await world.spent(mission.s256) == 60_000


async def test_a_call_over_budget_goes_to_a_person_before_the_access_server():
    world = World()
    ran = inline(world)
    mission = await world.approved_mission(budget=1_000)
    asked = await world.ask(mission, 60_000, aud=AS)
    assert ran == []
    assert (await world.follow(asked)).status_code == 202
    approval_id = urlsplit(asked.headers["location"]).path.rsplit("/", 1)[1]
    await world.ps.decide(
        TENANT,
        approval_id,
        ApprovalStatus.APPROVED,
        decided_by="dana",
    )
    assert ran == [approval_id]
    issued = await world.follow(asked)
    assert issued.status_code == 200, issued.text
    assert await world.spent(mission.s256) == 60_000


async def test_sub_agents_are_not_federated():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    token, person_token = world.resource_token(mission, 10, aud=AS)
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=token,
            presented_token=person_token,
            subagent_token="x",
        ),
    )
    assert refused.status_code == 400
    assert problem(refused).error == "invalid_request"


async def token_endpoint(world: World) -> str:
    metadata = await world.http.get(f"{AS}/.well-known/aauth-access.json")
    return body(metadata, AccessServerMetadata).auth_token_endpoint


async def test_an_access_server_that_cannot_be_reached_ends_as_unreachable():
    world = World()
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    world.net.failures[await token_endpoint(world)] = 1
    asked = await world.ask(mission, 60_000, aud=AS)
    answered = await world.follow(asked)
    assert answered.status_code == 502, answered.text
    assert problem(answered).error == "as_unreachable"
    assert await world.spent(mission.s256) == 0
