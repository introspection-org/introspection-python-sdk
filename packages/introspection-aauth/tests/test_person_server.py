"""The Person Server, three-party: missions, person tokens, auth tokens
within and over budget, approvals, completion."""

from urllib.parse import urlsplit

import pytest

from introspection_aauth.person_server import (
    ApprovalStatus,
    MemoryStore,
    Mission,
)
from introspection_aauth.protocol import AAuthError, SigningKey
from introspection_aauth.protocol.jwt import AGENT_TOKEN, decode, encode

from .world import AP, PS, RESOURCE, T0, TENANT, World, usd


def approval_id(response) -> str:
    return urlsplit(response.headers["location"]).path.rsplit("/", 1)[1]


async def test_publishes_its_metadata_and_keys():
    world = World()
    metadata = (
        await world.http.get(f"{PS}/.well-known/aauth-person.json")
    ).json()
    assert metadata["issuer"] == PS
    assert metadata["auth_token_endpoint"] == f"{PS}/aauth/token"
    keys = (await world.http.get(metadata["jwks_uri"])).json()
    assert keys == world.ps.jwks()


async def test_a_mission_goes_to_a_person_who_sets_its_budget():
    world = World()
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        {
            "description": "Book Sydney",
            "resources": [RESOURCE],
            "login_hint": "sam",
        },
    )
    assert proposed.status_code == 202
    assert proposed.headers["aauth-requirement"] == "requirement=approval"
    waiting = await world.follow(proposed)
    assert waiting.status_code == 202

    mission = await world.approved_mission(budget=100_000)
    blob = decode(mission["person_tokens"][RESOURCE]).claims
    assert blob["aud"] == RESOURCE and blob["mission_s256"] == mission["s256"]
    assert blob["tenant"] == TENANT


async def test_a_call_within_budget_is_issued_unasked_and_spent():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    issued = await world.ask(mission, 60_000)
    assert issued.status_code == 200, issued.text
    claims = decode(issued.json()["auth_token"]).claims
    assert claims["iss"] == PS and claims["aud"] == RESOURCE
    assert claims["budget"]["amount"] == 60_000
    assert await world.spent(mission["s256"]) == 60_000


async def test_a_call_over_budget_waits_on_a_person_then_is_issued():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    await world.ask(mission, 60_000)
    over = await world.ask(mission, 60_000)
    assert over.status_code == 202
    assert (await world.follow(over)).status_code == 202
    await world.ps.decide(
        TENANT, approval_id(over), ApprovalStatus.APPROVED, decided_by="dana"
    )
    issued = await world.follow(over)
    assert issued.status_code == 200, issued.text
    assert await world.spent(mission["s256"]) == 120_000


async def test_a_declined_call_is_refused():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    over = await world.ask(mission, 5_000)
    await world.ps.decide(
        TENANT, approval_id(over), ApprovalStatus.DENIED, decided_by="dana"
    )
    refused = await world.follow(over)
    assert refused.status_code == 403
    assert refused.json()["error"] == "denied"
    assert await world.spent(mission["s256"]) == 0


async def test_only_the_missions_person_accepts_its_completion():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    done = await world.call(
        "POST",
        f"{PS}/aauth/mission/{mission['s256']}",
        {"action": "completion", "summary": "Booked"},
    )
    assert done.status_code == 202
    with pytest.raises(AAuthError) as refused:
        await world.ps.decide(
            TENANT,
            approval_id(done),
            ApprovalStatus.APPROVED,
            decided_by="dana",
        )
    assert refused.value.status == 403
    await world.ps.decide(
        TENANT, approval_id(done), ApprovalStatus.APPROVED, decided_by="sam"
    )
    assert (await world.follow(done)).status_code == 200
    stored = await world.ps_store.mission(TENANT, mission["s256"])
    assert stored is not None and stored.completed_at == world.now
    after = await world.ask(mission, 10)
    assert after.status_code == 403
    assert after.json()["error"] == "mission_terminated"


async def test_a_mission_logs_updates():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    logged = await world.call(
        "POST",
        f"{PS}/aauth/mission/{mission['s256']}",
        {"action": "update", "description": "Found two flights"},
    )
    assert logged.status_code == 200
    stored = await world.ps_store.mission(TENANT, mission["s256"])
    assert stored is not None and stored.log[0].entry == "Found two flights"


async def test_an_unsigned_or_tampered_request_is_refused():
    world = World()
    unsigned = await world.http.post(f"{PS}/aauth/mission", json={})
    assert unsigned.status_code == 401
    signed = await world.call("GET", f"{PS}/aauth/pending/{TENANT}/nope")
    assert signed.status_code == 404


async def test_an_agent_from_an_untrusted_provider_is_refused():
    world = World()
    world.ps._providers = set()
    refused = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        {"description": "x", "login_hint": "sam"},
    )
    assert refused.status_code == 401
    assert refused.json()["error"] == "invalid_jwt"


async def test_a_key_acts_for_one_person():
    world = World()
    await world.approved_mission(budget=1_000)
    other = await world.call(
        "POST",
        f"{PS}/aauth/person-token",
        {"resource": RESOURCE, "login_hint": "someone-else"},
    )
    assert other.status_code == 403
    same = await world.call(
        "POST", f"{PS}/aauth/person-token", {"resource": RESOURCE}
    )
    assert same.status_code == 200
    claims = decode(same.json()["person_token"]).claims
    assert claims["sub"] == world.ps.directed_subject("sam", RESOURCE)


async def test_identical_missions_for_two_people_in_one_second_stay_apart():
    world = World()
    sam = await world.approved_mission(budget=100_000)
    # Another key of the same agent, acting for Kim, proposing the same mission
    # in the same second: the blob must still name a mission of Kim's own.
    world.agent_key = SigningKey.generate()
    world.agent_token = encode(
        {
            "iss": AP,
            "dwk": "aauth-agent.json",
            "sub": "aauth:travel@agents.example",
            "jti": "agent-2",
            "iat": T0,
            "exp": T0 + 3_600,
            "cnf": {"jwk": world.agent_key.public_jwk},
        },
        world.ap_key,
        AGENT_TOKEN,
    )
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        {
            "description": "Book Sydney",
            "resources": [RESOURCE],
            "login_hint": "kim",
        },
    )
    await world.ps.decide(
        TENANT,
        approval_id(proposed),
        ApprovalStatus.APPROVED,
        decided_by="dana",
        budget=usd(100_000),
    )
    kim = (await world.follow(proposed)).json()
    assert kim["s256"] != sam["s256"]
    sam_sub = decode(sam["person_tokens"][RESOURCE]).claims["sub"]
    kim_sub = decode(kim["person_tokens"][RESOURCE]).claims["sub"]
    assert kim_sub != sam_sub
    stored = await world.ps_store.mission(TENANT, kim["s256"])
    assert stored is not None and stored.person == "kim"


class TakenStore(MemoryStore):
    """A store where every mission hash is already taken."""

    async def insert_mission(self, tenant: str, mission: Mission) -> bool:
        return False


async def test_a_mission_whose_hash_is_taken_is_refused_not_reused():
    world = World(ps_store=TakenStore())
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        {
            "description": "Book Sydney",
            "resources": [RESOURCE],
            "login_hint": "sam",
        },
    )
    with pytest.raises(AAuthError) as refused:
        await world.ps.decide(
            TENANT,
            approval_id(proposed),
            ApprovalStatus.APPROVED,
            decided_by="dana",
            budget=usd(100_000),
        )
    assert refused.value.status == 409
    approval = await world.ps_store.approval(TENANT, approval_id(proposed))
    assert approval is not None and approval.status is ApprovalStatus.PENDING
