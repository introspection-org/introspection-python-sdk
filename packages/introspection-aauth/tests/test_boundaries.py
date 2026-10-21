"""What each server refuses at its edges: a second collect, a proposal off
its resource's origin, a malformed signature, an Access Server that throttles
or answers what is not served, and a Signature-Key naming a host to fetch."""

import asyncio
from urllib.parse import urlsplit

import httpx2 as httpx
import pytest

from introspection_aauth.access_server import PendingStatus, Verdict
from introspection_aauth.person_server import (
    Approval,
    ApprovalStatus,
    federation,
)
from introspection_aauth.person_server.models import (
    MissionAction,
    MissionProposal,
)
from introspection_aauth.protocol import SigningKey, VerificationError, httpsig
from introspection_aauth.protocol.claims import (
    AGENT_DWK,
    AgentTokenClaims,
    Confirmation,
)
from introspection_aauth.protocol.jwt import AGENT_TOKEN, encode
from introspection_aauth.protocol.keys import Jwk, verify
from introspection_aauth.protocol.wire import (
    AccessServerMetadata,
    TokenRequest,
)

from .test_federation import auth_token, inline
from .world import AP, AS, PS, RESOURCE, TENANT, World, problem, usd


def approval_id(response: httpx.Response) -> str:
    return urlsplit(response.headers["location"]).path.rsplit("/", 1)[1]


async def test_an_approved_auth_token_is_collected_once():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    over = await world.ask(mission, 5_000)
    await world.ps.decide(
        TENANT, approval_id(over), ApprovalStatus.APPROVED, decided_by="dana"
    )
    issued = await world.follow(over)
    assert issued.status_code == 200, issued.text
    again = await world.follow(over)
    assert again.status_code == 410
    assert problem(again).error == "invalid_code"
    assert await world.spent(mission.s256) == 5_000


async def test_an_approved_auth_token_not_collected_in_time_expires():
    world = World()
    world.ps._approval_ttl = 60
    mission = await world.approved_mission(budget=1_000)
    over = await world.ask(mission, 5_000)
    await world.ps.decide(
        TENANT, approval_id(over), ApprovalStatus.APPROVED, decided_by="dana"
    )
    world.now += 120
    late = await world.follow(over)
    assert late.status_code == 408


async def test_a_mission_approval_polled_after_the_mission_ended_is_refused():
    world = World()
    world.ps._mission_ttl = 60
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(
            description="Book Sydney", resources=[RESOURCE], login_hint="sam"
        ),
    )
    await world.ps.decide(
        TENANT,
        approval_id(proposed),
        ApprovalStatus.APPROVED,
        decided_by="dana",
        budget=usd(1_000),
    )
    world.now += 120
    ended = await world.follow(proposed)
    assert ended.status_code == 403
    assert problem(ended).error == "mission_terminated"


@pytest.mark.parametrize("decision", ["mission", "completion", "denied"])
async def test_a_pending_url_answers_once_then_is_gone(decision: str):
    world = World()
    mission = await world.approved_mission(budget=1_000)
    if decision == "mission":
        proposed = await world.call(
            "POST",
            f"{PS}/aauth/mission",
            MissionProposal(
                description="Again", resources=[RESOURCE], login_hint="sam"
            ),
        )
    else:
        proposed = await world.call(
            "POST",
            f"{PS}/aauth/mission/{mission.s256}",
            MissionAction(action="completion", summary="Done"),
        )
    await world.ps.decide(
        TENANT,
        approval_id(proposed),
        ApprovalStatus.DENIED
        if decision == "denied"
        else ApprovalStatus.APPROVED,
        decided_by="sam",
        budget=usd(1_000) if decision == "mission" else None,
    )
    first = await world.follow(proposed)
    assert first.status_code == (403 if decision == "denied" else 200)
    again = await world.follow(proposed)
    assert again.status_code == 410
    assert problem(again).error == "invalid_code"
    stored = await world.ps_store.select_approval(
        TENANT, approval_id(proposed)
    )
    assert stored is not None and stored.collected
    assert stored.status is (
        ApprovalStatus.DENIED
        if decision == "denied"
        else ApprovalStatus.APPROVED
    )


async def test_an_access_servers_refusal_is_answered_once():
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant: str, approval: Approval) -> None:
        kicked.append(approval.id)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    await world.ask(mission, 10, aud=AS)
    due = await world.ps.federation_due(TENANT, kicked[0])
    assert due is not None
    client = federation.AccessServerClient(world.ps)
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    first = await client.request(due[0], due[1], metadata)
    [pending] = list(world.access_store.requests.values())
    await world.access.decide(pending.id, False)
    assert first.location is not None
    denied = await client.poll(first.location, due[0], due[1], metadata)
    assert denied.refusal is not None and denied.refusal.status == 403
    gone = await client.poll(first.location, due[0], due[1], metadata)
    assert gone.refusal is not None and gone.refusal.status == 410
    [answered] = list(world.access_store.requests.values())
    assert answered.collected and answered.status is PendingStatus.DENIED


async def test_spends_against_one_mission_at_once_never_exceed_its_budget():
    world = World()
    mission = await world.approved_mission(budget=100_000)
    answers = await asyncio.gather(
        *(world.ask(mission, 60_000) for _ in range(3))
    )
    assert sorted(a.status_code for a in answers) == [200, 202, 202]
    assert await world.spent(mission.s256) == 60_000


async def test_an_agent_token_living_longer_than_an_hour_is_accepted():
    world = World()
    world.agent_token = encode(
        AgentTokenClaims(
            dwk=AGENT_DWK,
            iss=AP,
            sub="aauth:travel@agents.example",
            jti="agent-long",
            iat=world.now,
            exp=world.now + 12 * 3_600,
            cnf=Confirmation(jwk=world.agent_key.public_jwk),
        ),
        world.ap_key,
        AGENT_TOKEN,
    )
    assert (await world.approved_mission(budget=1_000)).s256


@pytest.mark.parametrize(
    "r3_uri",
    [
        "http://booking.example/r3/1",
        "https://internal.cluster.local/r3/1",
        "https://user:pass@booking.example/r3/1",
        "https://10.0.0.5/r3/1",
    ],
)
async def test_a_proposal_is_read_only_from_its_resources_https_origin(
    r3_uri: str,
):
    world = World()
    with pytest.raises(ValueError, match="origin"):
        await world.ps.identity.read_proposal(
            world.http, RESOURCE, r3_uri, "x", world.now
        )
    assert world.net.calls == []


async def test_a_signature_that_is_a_list_is_refused():
    world = World()
    url = f"{PS}/aauth/mission"
    headers = httpsig.sign(
        world.agent_key,
        httpsig.jwt_key(world.agent_token),
        "GET",
        url,
        created=world.now,
    )
    request = httpsig.SignedRequest(
        "GET", url, headers | {"signature": 'sig=("a")'}
    )
    with pytest.raises(VerificationError) as refused:
        await httpsig.verify(request, world.now)
    assert refused.value.code == "invalid_signature"


async def test_a_body_signed_without_its_content_type_is_refused():
    world = World()
    url = f"{PS}/aauth/mission"
    headers = httpsig.sign(
        world.agent_key,
        httpsig.jwt_key(world.agent_token),
        "POST",
        url,
        body=b"{}",
        created=world.now,
    )
    params = headers["signature-input"].replace(' "content-type"', "")
    request = httpsig.SignedRequest(
        "POST", url, headers | {"signature-input": params}, b"{}"
    )
    with pytest.raises(VerificationError) as refused:
        await httpsig.verify(request, world.now)
    assert refused.value.detail == "content-type must be covered"


async def test_a_signature_key_naming_a_host_fetches_nothing():
    world = World()
    for url, signature_key in (
        (
            f"{PS}/aauth/mission",
            'sig=jwks_uri;id="http://169.254.169.254/latest";dwk="x";kid="k"',
        ),
        (
            f"{AS}/token",
            'sig=jwks_uri;id="http://169.254.169.254/latest";dwk="aauth-person.json";kid="k"',
        ),
        (
            f"{AS}/token",
            f'sig=jwks_uri;id="{PS}";dwk="aauth-agent.json";kid="k"',
        ),
    ):
        world.net.calls.clear()
        headers = httpsig.sign(
            SigningKey.generate(),
            signature_key,
            "POST",
            url,
            body=b"{}",
            created=world.now,
        )
        refused = await world.http.post(url, content=b"{}", headers=headers)
        assert refused.status_code == 401
        assert world.net.calls == [f"POST {url}"], world.net.calls


class Scripted(httpx.AsyncBaseTransport):
    """The Access Server, with its first answers to `/token` replaced."""

    def __init__(
        self, app: httpx.AsyncBaseTransport, *answers: httpx.Response
    ):
        self.app = app
        self.answers = list(answers)

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        if request.url.path == "/token" and self.answers:
            await request.aread()
            return self.answers.pop(0)
        return await self.app.handle_async_request(request)


async def federate(world: World, *answers: httpx.Response) -> httpx.Response:
    inline(world)
    world.net.apps[AS] = Scripted(world.net.apps[AS], *answers)
    mission = await world.approved_mission(budget=100_000)
    return await world.follow(await world.ask(mission, 60_000, aud=AS))


@pytest.mark.parametrize("status", [429, 503])
async def test_a_throttled_first_request_is_sent_again(status: int):
    world = World()
    issued = await federate(
        world, httpx.Response(status, headers={"Retry-After": "1"})
    )
    assert issued.status_code == 200, issued.text
    assert auth_token(issued).iss == AS
    posts = [c for c in world.net.calls if c == f"POST {AS}/token"]
    assert len(posts) == 2


async def test_an_access_server_asking_for_payment_is_refused():
    refused = await federate(World(), httpx.Response(402))
    assert refused.status_code == 403
    assert problem(refused).error == "denied"


async def test_a_pending_location_on_another_origin_is_as_unreachable():
    refused = await federate(
        World(),
        httpx.Response(
            202, headers={"Location": "https://elsewhere.example/p"}
        ),
    )
    assert refused.status_code == 502
    assert problem(refused).error == "as_unreachable"


async def test_an_unknown_requirement_is_relayed_as_approval():
    world = World(policy=lambda request: Verdict.approval())
    kicked: list[str] = []

    async def kick(tenant: str, approval: Approval) -> None:
        kicked.append(tenant)

    world.ps._on_federate = kick
    mission = await world.approved_mission(budget=100_000)
    asked = await world.ask(mission, 60_000, aud=AS)
    approval = urlsplit(asked.headers["location"]).path.rsplit("/", 1)[1]
    due = await world.ps.federation_due(TENANT, approval)
    assert due is not None
    client = federation.AccessServerClient(world.ps)
    metadata = await client.discover(due[0].access_server)
    assert isinstance(metadata, federation.Metadata)
    world.net.apps[AS] = Scripted(
        world.net.apps[AS],
        httpx.Response(
            202,
            headers={
                "AAuth-Requirement": "requirement=telepathy",
                "Location": "/pending/1",
            },
        ),
    )
    outcome = await client.request(due[0], due[1], metadata)
    assert outcome.step is federation.Step.PENDING
    assert outcome.requirement == "requirement=approval"


async def test_a_mission_action_is_update_or_completion():
    world = World()
    mission = await world.approved_mission(budget=1_000)
    refused = await world.call_raw(
        "POST",
        f"{PS}/aauth/mission/{mission.s256}",
        b'{"action":"cancel"}',
    )
    assert refused.status_code == 400
    assert problem(refused).error == "invalid_request"
    logged = await world.call(
        "POST",
        f"{PS}/aauth/mission/{mission.s256}",
        MissionAction(action="update", description="x"),
    )
    assert logged.status_code == 200


async def test_a_token_request_body_is_its_model():
    assert TokenRequest(
        resource_token="r", agent_token="a", presented_token="p"
    ).to_json() == (
        b'{"resource_token":"r","agent_token":"a","presented_token":"p"}'
    )


@pytest.mark.parametrize("tenant", ["org:proj", "a b%c", "a%41"])
async def test_a_tenant_that_needs_escaping_polls_through_the_router(
    tenant: str,
):
    world = World()
    world.ps._default_tenant = tenant
    proposed = await world.call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(
            description="Book Sydney", resources=[RESOURCE], login_hint="sam"
        ),
    )
    assert proposed.status_code == 202, proposed.text
    waiting = await world.follow(proposed)
    assert waiting.status_code == 202, waiting.text
    await world.ps.decide(
        tenant,
        approval_id(proposed),
        ApprovalStatus.APPROVED,
        decided_by="dana",
        budget=usd(1_000),
    )
    approved = await world.follow(proposed)
    assert approved.status_code == 200, approved.text


@pytest.mark.parametrize(
    ("auth_token_endpoint", "jwks_uri"),
    [
        ("https://elsewhere.example/token", f"{AS}/jwks.json"),
        (f"{AS}/token", "https://elsewhere.example/jwks.json"),
        ("https://user@as.booking.example/token", f"{AS}/jwks.json"),
    ],
)
async def test_access_server_metadata_keeps_its_endpoints_on_its_origin(
    auth_token_endpoint: str, jwks_uri: str
):
    world = World()
    world.net.documents[f"{AS}/.well-known/aauth-access.json"] = (
        AccessServerMetadata(
            issuer=AS,
            jwks_uri=jwks_uri,
            auth_token_endpoint=auth_token_endpoint,
        )
    )
    found = await federation.AccessServerClient(world.ps).discover(AS)
    assert isinstance(found, federation.Outcome)
    assert found.refusal is not None
    assert found.refusal.error == "as_unreachable"


async def test_an_agent_key_without_alg_takes_its_algorithm_from_its_type():
    world = World()
    world.agent_token = encode(
        AgentTokenClaims(
            dwk=AGENT_DWK,
            iss=AP,
            sub="aauth:travel@agents.example",
            jti="agent-no-alg",
            iat=world.now,
            exp=world.now + 3_600,
            cnf=Confirmation(
                jwk=world.agent_key.public_jwk.model_copy(
                    update={"alg": None, "kid": None, "use": None}
                )
            ),
        ),
        world.ap_key,
        AGENT_TOKEN,
    )
    assert (await world.approved_mission(budget=1_000)).s256


def test_a_key_type_with_no_supported_algorithm_is_refused():
    key = SigningKey.generate()
    for jwk in (
        key.public_jwk.model_copy(update={"alg": None, "crv": "X25519"}),
        key.public_jwk.model_copy(update={"alg": "RS256"}),
        Jwk(kty="oct"),
    ):
        assert not verify(jwk, b"data", key.sign(b"data"))
    assert verify(
        key.public_jwk.model_copy(update={"alg": None}),
        b"data",
        key.sign(b"data"),
    )
