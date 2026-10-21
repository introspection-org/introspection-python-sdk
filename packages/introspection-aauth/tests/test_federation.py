"""Four-party (`#access-server-federation`): the Person Server weighs the
call against the mission, then redeems it at the resource's Access Server."""

from urllib.parse import urlsplit

from introspection_aauth.access_server import Verdict
from introspection_aauth.person_server import ApprovalStatus, federation
from introspection_aauth.protocol.jwt import decode

from .world import AS, PS, RESOURCE, TENANT, World, usd


def inline(world: World) -> list[str]:
    """Run each federation to its end before the agent's request is answered."""
    ran: list[str] = []

    async def run(tenant: str, approval) -> None:
        ran.append(approval.id)

        async def no_wait(_: float) -> None:
            return None

        await federation.run(world.ps, tenant, approval.id, sleep=no_wait)

    world.ps._on_federate = run
    return ran


async def test_the_access_server_publishes_its_metadata():
    world = World()
    metadata = (
        await world.http.get(f"{AS}/.well-known/aauth-access.json")
    ).json()
    assert metadata["auth_token_endpoint"] == f"{AS}/token"
    keys = (await world.http.get(metadata["jwks_uri"])).json()
    assert keys == world.access.jwks()


async def test_an_allowed_call_is_issued_by_the_access_server_and_collected_once():
    world = World()
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 60_000, aud=AS)
    issued = await world.follow(asked)
    assert issued.status_code == 200, issued.text
    claims = decode(issued.json()["auth_token"]).claims
    assert (
        claims["iss"] == AS
        and claims["aud"] == RESOURCE
        and claims["ps"] == PS
    )
    assert claims["cnf"]["jwk"]["x"] == world.agent_key.public_jwk["x"]
    assert await world.spent(mission["s256"]) == 60_000
    again = await world.follow(asked)
    assert again.status_code == 410
    assert again.json()["error"] == "invalid_code"


async def test_a_refusal_is_relayed_and_nothing_is_spent():
    world = World(
        policy=lambda request: Verdict.deny("no Flight Sector account")
    )
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    refused = await world.follow(await world.ask(mission, 60_000, aud=AS))
    assert refused.status_code == 403
    assert refused.json()["error"] == "denied"
    assert "no Flight Sector account" in refused.json()["detail"]
    assert await world.spent(mission["s256"]) == 0


async def test_a_smaller_grant_is_all_that_is_spent():
    world = World(policy=lambda request: Verdict.allow(budget=usd(40_000)))
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    issued = await world.follow(await world.ask(mission, 60_000, aud=AS))
    assert issued.status_code == 200, issued.text
    assert (
        decode(issued.json()["auth_token"]).claims["budget"]["amount"]
        == 40_000
    )
    assert await world.spent(mission["s256"]) == 40_000


async def test_the_access_servers_wait_is_journaled_step_by_step():
    """What a durable host does: each step is one call it can record."""
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant: str, approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 60_000, aud=AS)
    approval_id = kicked[0]

    due = await federation.due(world.ps, TENANT, approval_id)
    assert due is not None
    fed, jkt = due
    client = federation.AccessServerClient(world.ps)
    metadata = await client.discover(fed.access_server)
    assert isinstance(metadata, federation.Metadata)
    outcome = await client.request(fed, jkt, metadata)
    assert outcome.step is federation.Step.PENDING
    assert await federation.record(world.ps, TENANT, approval_id, outcome)
    waiting = await world.follow(asked)
    assert waiting.status_code == 202
    assert waiting.headers["aauth-requirement"] == "requirement=approval"

    [pending] = list(world.access_store.requests.values())
    assert pending.request.budget == usd(60_000)
    await world.access.decide(pending.id, True, decided_by="flight-sector")
    assert outcome.location is not None
    outcome = await client.poll(outcome.location, fed, jkt, metadata)
    assert outcome.step is federation.Step.ISSUED
    assert not await federation.record(world.ps, TENANT, approval_id, outcome)
    assert (await world.follow(asked)).status_code == 200
    assert await world.spent(mission["s256"]) == 60_000


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
    assert await world.spent(mission["s256"]) == 60_000


async def test_sub_agents_are_not_federated():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    token, person_token = world.resource_token(mission, 10, aud=AS)
    refused = await world.call(
        "POST",
        f"{PS}/aauth/token",
        {
            "resource_token": token,
            "presented_token": person_token,
            "subagent_token": "x",
        },
    )
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_request"
