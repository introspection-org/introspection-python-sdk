"""The Person Server, three-party: missions, person tokens, auth tokens
within and over budget, approvals, completion."""

from urllib.parse import urlsplit

import httpx2 as httpx
import pytest

from introspection_aauth.person_server import (
    ApprovalStatus,
    MemoryStore,
    Mission,
)
from introspection_aauth.person_server.models import (
    AuthTokenRequest,
    MissionAction,
    MissionAnswer,
    MissionProposal,
    PersonTokenRequest,
)
from introspection_aauth.protocol import AAuthError, SigningKey, jwt
from introspection_aauth.protocol.claims import (
    AGENT_DWK,
    AgentTokenClaims,
    AuthTokenClaims,
    Confirmation,
    PersonTokenClaims,
)
from introspection_aauth.protocol.jwt import (
    AGENT_TOKEN,
    AUTH_TOKEN,
    RESOURCE_TOKEN,
    encode,
)
from introspection_aauth.protocol.keys import Jwks
from introspection_aauth.protocol.wire import (
    AuthTokenAnswer,
    PersonServerMetadata,
    PersonTokenAnswer,
)

from .world import (
    AP,
    PS,
    RESOURCE,
    T0,
    TENANT,
    World,
    body,
    problem,
    read,
    usd,
)


def approval_id(response: httpx.Response) -> str:
    return urlsplit(response.headers["location"]).path.rsplit("/", 1)[1]


async def test_publishes_its_metadata_and_keys():
    world = World()
    metadata = body(
        await world.http.get(f"{PS}/.well-known/aauth-person.json"),
        PersonServerMetadata,
    )
    assert metadata == world.ps.metadata()
    assert metadata.auth_token_endpoint == f"{PS}/aauth/token"
    keys = body(await world.http.get(metadata.jwks_uri), Jwks)
    assert keys == world.ps.jwks()


async def test_a_mission_goes_to_a_person_who_sets_its_budget():
    world = World()
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(
            description="Book Sydney",
            resources=[RESOURCE],
            login_hint="sam",
        ),
    )
    assert proposed.status_code == 202
    assert proposed.headers["aauth-requirement"] == "requirement=approval"
    waiting = await world.follow(proposed)
    assert waiting.status_code == 202

    mission = await world.approved_mission(budget=100_000)
    claims = read(mission.person_tokens[RESOURCE], PersonTokenClaims)
    assert claims.aud == RESOURCE and claims.mission_s256 == mission.s256
    assert claims.tenant == TENANT


async def test_a_call_within_budget_is_issued_unasked_and_spent():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    issued = await world.ask(mission, 60_000)
    assert issued.status_code == 200, issued.text
    claims = read(body(issued, AuthTokenAnswer).auth_token, AuthTokenClaims)
    assert claims.iss == PS and claims.aud == RESOURCE
    assert claims.budget == usd(60_000)
    assert await world.spent(mission.s256) == 60_000


async def present(
    world: World,
    mission: MissionAnswer,
    amount: int,
    presented: str,
    **update: str,
) -> httpx.Response:
    """A call whose resource saw `presented`, with its resource token changed by `update`."""
    seen = str(jwt.decode(presented).claims["jti"])
    rt = world.resource_claims(mission, amount).model_copy(
        update={
            "jti": f"rt-{seen}",
            "presented_jti": seen,
            **update,
        }
    )
    return await world.call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=encode(rt, world.resource_key, RESOURCE_TOKEN),
            presented_token=presented,
        ),
    )


async def test_a_second_call_presents_the_first_calls_auth_token():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    first = body(await world.ask(mission, 30_000), AuthTokenAnswer).auth_token
    second = await present(world, mission, 40_000, first)
    assert second.status_code == 200, second.text
    claims = read(body(second, AuthTokenAnswer).auth_token, AuthTokenClaims)
    assert claims.budget == usd(40_000)
    assert await world.spent(mission.s256) == 70_000


async def test_a_presented_auth_token_must_be_the_one_the_resource_saw():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    first = body(await world.ask(mission, 30_000), AuthTokenAnswer).auth_token
    refused = await present(
        world, mission, 40_000, first, presented_jti="other"
    )
    assert refused.status_code == 400
    assert problem(refused).error == "invalid_resource_token"


async def test_an_auth_token_this_person_server_did_not_issue_is_refused():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    first = body(await world.ask(mission, 30_000), AuthTokenAnswer).auth_token
    claims = read(first, AuthTokenClaims)
    foreign = encode(
        claims.model_copy(update={"jti": "at-foreign"}),
        SigningKey.generate(),
        AUTH_TOKEN,
    )
    refused = await present(world, mission, 40_000, foreign)
    assert refused.status_code == 400
    assert problem(refused).error == "invalid_presented_token"


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
    assert await world.spent(mission.s256) == 120_000


async def test_a_declined_call_is_refused():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    over = await world.ask(mission, 5_000)
    await world.ps.decide(
        TENANT, approval_id(over), ApprovalStatus.DENIED, decided_by="dana"
    )
    refused = await world.follow(over)
    assert refused.status_code == 403
    assert problem(refused).error == "denied"
    assert await world.spent(mission.s256) == 0


async def test_only_the_missions_person_accepts_its_completion():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    done = await world.call(
        "POST",
        f"{PS}/aauth/mission/{mission.s256}",
        MissionAction(action="completion", summary="Booked"),
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
    stored = await world.ps_store.select_mission(TENANT, mission.s256)
    assert stored is not None and stored.completed_at == world.now
    after = await world.ask(mission, 10)
    assert after.status_code == 403
    assert problem(after).error == "mission_terminated"


async def test_a_mission_logs_updates():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    logged = await world.call(
        "POST",
        f"{PS}/aauth/mission/{mission.s256}",
        MissionAction(action="update", description="Found two flights"),
    )
    assert logged.status_code == 200
    stored = await world.ps_store.select_mission(TENANT, mission.s256)
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
        MissionProposal(description="x", login_hint="sam"),
    )
    assert refused.status_code == 401
    assert problem(refused).error == "invalid_jwt"


async def test_a_key_acts_for_one_person():
    world = World()
    await world.approved_mission(budget=1_000)
    other = await world.call(
        "POST",
        f"{PS}/aauth/person-token",
        PersonTokenRequest(resource=RESOURCE, login_hint="someone-else"),
    )
    assert other.status_code == 403
    same = await world.call(
        "POST",
        f"{PS}/aauth/person-token",
        PersonTokenRequest(resource=RESOURCE),
    )
    assert same.status_code == 200
    claims = read(
        body(same, PersonTokenAnswer).person_token, PersonTokenClaims
    )
    assert claims.sub == world.ps.directed_subject("sam", RESOURCE)


async def test_identical_missions_for_two_people_in_one_second_stay_apart():
    world = World()
    sam = await world.approved_mission(budget=100_000)
    # Another key of the same agent, acting for Kim, proposing the same mission
    # in the same second: the blob must still name a mission of Kim's own.
    world.agent_key = SigningKey.generate()
    world.agent_token = encode(
        AgentTokenClaims(
            dwk=AGENT_DWK,
            iss=AP,
            sub="aauth:travel@agents.example",
            jti="agent-2",
            iat=T0,
            exp=T0 + 3_600,
            cnf=Confirmation(jwk=world.agent_key.public_jwk),
        ),
        world.ap_key,
        AGENT_TOKEN,
    )
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(
            description="Book Sydney",
            resources=[RESOURCE],
            login_hint="kim",
        ),
    )
    await world.ps.decide(
        TENANT,
        approval_id(proposed),
        ApprovalStatus.APPROVED,
        decided_by="dana",
        budget=usd(100_000),
    )
    kim = body(await world.follow(proposed), MissionAnswer)
    assert kim.s256 != sam.s256
    sam_sub = read(sam.person_tokens[RESOURCE], PersonTokenClaims).sub
    kim_sub = read(kim.person_tokens[RESOURCE], PersonTokenClaims).sub
    assert kim_sub != sam_sub
    stored = await world.ps_store.select_mission(TENANT, kim.s256)
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
        MissionProposal(
            description="Book Sydney",
            resources=[RESOURCE],
            login_hint="sam",
        ),
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
    approval = await world.ps_store.select_approval(
        TENANT, approval_id(proposed)
    )
    assert approval is not None and approval.status is ApprovalStatus.PENDING


async def propose(world: World) -> str:
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(
            description="Book Sydney",
            resources=[RESOURCE],
            login_hint="sam",
        ),
    )
    return approval_id(proposed)


async def test_a_decision_in_the_callers_unit_of_work_commits_with_it():
    world = World()
    pending = await propose(world)
    async with world.ps_store.transaction() as tx:
        decided = await world.ps.decide(
            TENANT,
            pending,
            ApprovalStatus.APPROVED,
            decided_by="dana",
            budget=usd(100_000),
            store=tx,
        )
    assert decided is not None and decided.mission_s256 is not None
    await world.ps.decided(TENANT, decided)
    assert (
        await world.ps_store.select_mission(TENANT, decided.mission_s256)
        is not None
    )


async def test_a_decision_in_the_callers_unit_of_work_rolls_back_with_it():
    world = World()
    pending = await propose(world)
    with pytest.raises(RuntimeError):
        async with world.ps_store.transaction() as tx:
            decided = await world.ps.decide(
                TENANT,
                pending,
                ApprovalStatus.APPROVED,
                decided_by="dana",
                budget=usd(100_000),
                store=tx,
            )
            raise RuntimeError("the host's own write failed")
    assert decided is not None and decided.mission_s256 is not None
    assert (
        await world.ps_store.select_mission(TENANT, decided.mission_s256)
        is None
    )
    approval = await world.ps_store.select_approval(TENANT, pending)
    assert approval is not None and approval.status is ApprovalStatus.PENDING
