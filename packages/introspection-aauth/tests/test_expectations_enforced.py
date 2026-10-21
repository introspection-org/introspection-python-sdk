"""Each server refuses a token that is valid on its own but not the one it
expected: dropping an expectation check fails one of these."""

import httpx2 as httpx
import pytest

from introspection_aauth.person_server.models import MissionAnswer
from introspection_aauth.protocol import SigningKey
from introspection_aauth.protocol.claims import (
    AGENT_DWK,
    AgentTokenClaims,
    AuthTokenClaims,
    Confirmation,
    ResourceTokenClaims,
)
from introspection_aauth.protocol.jwt import (
    AGENT_TOKEN,
    AUTH_TOKEN,
    RESOURCE_TOKEN,
    decode,
    encode,
)
from introspection_aauth.protocol.wire import AuthTokenAnswer, TokenRequest

from .test_federation import inline
from .world import AP, AS, T0, World, problem

OTHER = SigningKey.generate()


async def redeem(
    world: World,
    mission: MissionAnswer,
    rt: ResourceTokenClaims,
    agent_token: str | None = None,
) -> httpx.Response:
    """The Person Server's token request to the Access Server, for `rt`."""
    content = TokenRequest(
        resource_token=encode(rt, world.resource_key, RESOURCE_TOKEN),
        agent_token=agent_token or world.agent_token,
        presented_token=mission.person_tokens[rt.iss],
    ).to_json()
    url = f"{AS}/token"
    headers = world.ps.identity.signed("POST", url, content, world.now)
    return await world.http.post(url, content=content, headers=headers)


async def redeem_with(
    world: World, agent_token: str | None = None, **update: str
) -> httpx.Response:
    """`redeem`, for a resource token changed by `update`."""
    mission = await world.approved_mission(budget=100_000)
    rt = world.resource_claims(mission, 10, aud=AS).model_copy(update=update)
    return await redeem(world, mission, rt, agent_token)


async def test_the_access_server_redeems_the_expected_tokens():
    world = World()
    answered = await redeem_with(world)
    assert answered.status_code == 200, answered.text


async def test_the_access_server_refuses_an_agent_token_bound_elsewhere():
    world = World()
    answered = await redeem_with(world, agent_jkt=OTHER.kid)
    assert answered.status_code == 400
    assert problem(answered).error == "invalid_resource_token"


async def test_the_access_server_refuses_an_agent_token_for_another_person_server():
    world = World()
    agent_token = encode(
        AgentTokenClaims(
            iss=AP,
            dwk=AGENT_DWK,
            sub="aauth:travel@agents.example",
            jti="agent-2",
            iat=T0,
            exp=T0 + 3_600,
            cnf=Confirmation(jwk=world.agent_key.public_jwk),
            ps="https://other-ps.example",
        ),
        world.ap_key,
        AGENT_TOKEN,
    )
    answered = await redeem_with(world, agent_token)
    assert answered.status_code == 400
    assert problem(answered).error == "invalid_request"


@pytest.mark.parametrize(
    "update",
    [{"presented_jti": "pt-other"}, {"sub": "person-other"}],
)
async def test_the_access_server_refuses_a_resource_token_not_naming_the_presented_token(
    update: dict[str, str],
):
    world = World()
    answered = await redeem_with(world, **update)
    assert answered.status_code == 400
    assert problem(answered).error == "invalid_resource_token"


class Tampering(httpx.AsyncBaseTransport):
    """The Access Server, re-signing the auth token it issues with `update`."""

    def __init__(
        self,
        world: World,
        app: httpx.AsyncBaseTransport,
        update: dict[str, str | Confirmation],
    ):
        self.world, self.app, self.update = world, app, update

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        response = await self.app.handle_async_request(request)
        if request.url.path != "/token" or response.status_code != 200:
            return response
        await response.aread()
        answer = AuthTokenAnswer.model_validate_json(response.content)
        claims = AuthTokenClaims.model_validate(
            decode(answer.auth_token).claims
        ).model_copy(update=self.update)
        token = self.world.access.identity.token(claims, AUTH_TOKEN)
        return httpx.Response(
            200,
            content=answer.model_copy(update={"auth_token": token}).to_json(),
            headers={"Content-Type": "application/json"},
        )


@pytest.mark.parametrize(
    "update",
    [
        {"sub": "person-other"},
        {"aud": "https://elsewhere.example"},
        {"scope": "book cancel"},
        {"ps": "https://other-ps.example"},
        {"cnf": Confirmation(jwk=OTHER.public_jwk)},
    ],
)
async def test_the_person_server_refuses_an_auth_token_it_did_not_ask_for(
    update: dict[str, str | Confirmation],
):
    world = World()
    inline(world)
    world.net.apps[AS] = Tampering(world, world.net.apps[AS], update)
    mission = await world.approved_mission(budget=100_000)
    answered = await world.follow(await world.ask(mission, 60_000, aud=AS))
    assert answered.status_code == 502, answered.text
    assert problem(answered).error == "as_unreachable"
    assert await world.spent(mission.s256) == 0
