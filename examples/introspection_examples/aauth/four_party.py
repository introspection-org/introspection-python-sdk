"""A Person Server and an Access Server on FastAPI, and AAuth's four-party
flow through them (draft-hardt-oauth-aauth-protocol -11).

An agent proposes a trip, the traveller's manager approves it with a
budget, and the agent books with the airline. The airline's resource tokens
name its own Access Server, so the Person Server weighs the booking against
the trip's budget, then redeems it there; the airline's policy books only
for companies with an account. Every party runs in this process on
in-memory stores, joined by one in-process transport; no network, no keys
to configure, nothing to install beyond the examples project.

Run the whole flow:

    uv run -m introspection_examples.aauth.four_party

Or serve the two servers for your own agents, each on its own https origin
(a tunnel in front of each), with the agent provider you trust:

    PERSON_SERVER=https://ps.example AGENT_PROVIDER=https://agents.example \\
        uv run --with uvicorn uvicorn --factory introspection_examples.aauth.four_party:serve_person_server --port 8001
    ACCESS_SERVER=https://as.example RESOURCE=https://booking.example \\
        PERSON_SERVER=https://ps.example AGENT_PROVIDER=https://agents.example \\
        uv run --with uvicorn uvicorn --factory introspection_examples.aauth.four_party:serve_access_server --port 8002
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx2 as httpx
from fastapi import FastAPI
from introspection_aauth.access_server import (
    AccessRequest,
    AccessServer,
    Verdict,
)
from introspection_aauth.fastapi import (
    access_server_router,
    person_server_router,
)
from introspection_aauth.person_server import (
    ApprovalStatus,
    MemoryStore,
    PersonServer,
)
from introspection_aauth.person_server.models import (
    AuthTokenRequest,
    MissionAnswer,
    MissionProposal,
)
from introspection_aauth.protocol import Budget, SigningKey, jwks
from introspection_aauth.protocol.claims import (
    AGENT_DWK,
    RESOURCE_DWK,
    AgentTokenClaims,
    AuthTokenClaims,
    Confirmation,
    PersonTokenClaims,
    ResourceTokenClaims,
)
from introspection_aauth.protocol.httpsig import jwt_key, sign
from introspection_aauth.protocol.jwt import (
    AGENT_TOKEN,
    RESOURCE_TOKEN,
    decode,
    encode,
)
from introspection_aauth.protocol.wire import (
    AuthTokenAnswer,
    ServerMetadata,
)
from pydantic import BaseModel

AP = os.environ.get("AGENT_PROVIDER", "https://agents.example")
PS = os.environ.get("PERSON_SERVER", "https://ps.example")
AS = os.environ.get("ACCESS_SERVER", "https://as.flightsector.example")
RESOURCE = os.environ.get("RESOURCE", "https://booking.flightsector.example")
TENANT = "acme"


def usd(amount: int) -> Budget:
    return Budget(amount=amount, unit="USD", decimals=2)


# #region docs:aauth-servers
def flight_sector(request: AccessRequest) -> Verdict:
    """The airline's policy: it books only for companies with an account."""
    if (request.tenant, request.ps) == (TENANT, PS):
        return Verdict.allow()
    return Verdict.deny("no Flight Sector account")


def person_server(http: httpx.AsyncClient) -> PersonServer:
    return PersonServer(
        PS,
        SigningKey.generate(),
        MemoryStore(),
        subject_secret=os.urandom(32),
        agent_providers=[AP],
        http=http,
        endpoint_base=f"{PS}/aauth",
        default_tenant=TENANT,
    )


def access_server(http: httpx.AsyncClient) -> AccessServer:
    return AccessServer(
        AS,
        SigningKey.generate(),
        flight_sector,
        resources=[RESOURCE],
        person_servers=[PS],
        agent_providers=[AP],
        http=http,
    )


# #endregion docs:aauth-servers


def closing(
    http: httpx.AsyncClient,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """A lifespan that closes the server's http client when the app stops."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await http.aclose()

    return lifespan


# #region docs:aauth-apps
def person_server_app(ps: PersonServer) -> FastAPI:
    app = FastAPI(lifespan=closing(ps.http))
    app.include_router(person_server_router(ps))
    return app


def access_server_app(server: AccessServer) -> FastAPI:
    app = FastAPI(lifespan=closing(server.http))
    app.include_router(access_server_router(server))
    return app


# #endregion docs:aauth-apps


def serve_person_server() -> FastAPI:
    """For `uvicorn --factory`: a Person Server with its own http client."""
    return person_server_app(person_server(httpx.AsyncClient()))


def serve_access_server() -> FastAPI:
    """For `uvicorn --factory`: an Access Server with its own http client."""
    return access_server_app(access_server(httpx.AsyncClient()))


class Internet(httpx.AsyncBaseTransport):
    """Routes each origin to its party, in this process."""

    def __init__(self) -> None:
        self.parties: dict[str, httpx.AsyncBaseTransport] = {}
        self.documents: dict[str, BaseModel] = {}

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        document = self.documents.get(str(request.url))
        if document is not None:
            return httpx.Response(
                200,
                content=document.model_dump_json(exclude_none=True),
                headers={"Content-Type": "application/json"},
            )
        origin = f"{request.url.scheme}://{request.url.host}"
        print(f"  → {request.method} {request.url}")
        return await self.parties[origin].handle_async_request(request)


async def main() -> None:
    internet = Internet()
    async with httpx.AsyncClient(transport=internet) as http:
        await run(internet, http)


async def run(internet: Internet, http: httpx.AsyncClient) -> None:
    ps = person_server(http)
    internet.parties[PS] = httpx.ASGITransport(app=person_server_app(ps))
    internet.parties[AS] = httpx.ASGITransport(
        app=access_server_app(access_server(http))
    )

    # The agent provider and the airline's booking API, as fixed documents.
    provider, airline, agent = (SigningKey.generate() for _ in range(3))
    internet.documents |= {
        f"{AP}/.well-known/aauth-agent.json": ServerMetadata(
            issuer=AP, jwks_uri=f"{AP}/jwks.json"
        ),
        f"{AP}/jwks.json": jwks([provider]),
        f"{RESOURCE}/.well-known/aauth-resource.json": ServerMetadata(
            issuer=RESOURCE, jwks_uri=f"{RESOURCE}/jwks.json"
        ),
        f"{RESOURCE}/jwks.json": jwks([airline]),
    }
    now = ps.clock()
    agent_token = encode(
        AgentTokenClaims(
            dwk=AGENT_DWK,
            iss=AP,
            sub="aauth:travel@agents.example",
            jti="agent-1",
            iat=now,
            exp=now + 3_600,
            cnf=Confirmation(jwk=agent.public_jwk),
        ),
        provider,
        AGENT_TOKEN,
    )

    async def call(
        method: str, url: str, body: BaseModel | None = None
    ) -> httpx.Response:
        content = (
            body.model_dump_json(exclude_none=True).encode()
            if body is not None
            else None
        )
        headers = sign(
            agent,
            jwt_key(agent_token),
            method,
            url,
            body=content,
            created=ps.clock(),
        )
        return await http.request(
            method, url, content=content, headers=headers
        )

    print("1. The agent proposes the trip")
    proposed = await call(
        "POST",
        f"{PS}/aauth/mission",
        MissionProposal(
            description="Sam to Sydney, up to $2,000",
            resources=[RESOURCE],
            login_hint="sam@acme.example",
        ),
    )
    print(f"   {proposed.status_code}: it waits on Sam's manager")
    approval_id = proposed.headers["location"].rsplit("/", 1)[1]
    await ps.decide(
        TENANT,
        approval_id,
        ApprovalStatus.APPROVED,
        decided_by="dana@acme.example",
        budget=usd(200_000),
    )
    collected = await call("GET", proposed.headers["location"])
    mission = MissionAnswer.model_validate_json(collected.content)
    print("2. Dana approves it with a $2,000 budget; the agent collects it")

    person_token = mission.person_tokens[RESOURCE]
    presented = PersonTokenClaims.model_validate(decode(person_token).claims)
    resource_token = encode(
        ResourceTokenClaims(
            dwk=RESOURCE_DWK,
            jti="quote-1",
            iss=RESOURCE,
            aud=AS,
            ps=PS,
            agent_jkt=agent.kid,
            presented_jti=presented.jti,
            sub=presented.sub,
            mission_s256=mission.s256,
            tenant=TENANT,
            scope="book",
            budget=usd(145_000),
            iat=now,
            exp=now + 300,
        ),
        airline,
        RESOURCE_TOKEN,
    )
    print("3. The airline quotes $1,450 and asks for an auth token")
    asked = await call(
        "POST",
        f"{PS}/aauth/token",
        AuthTokenRequest(
            resource_token=resource_token, presented_token=person_token
        ),
    )
    print(f"   {asked.status_code}: within budget, so off to the airline's AS")
    for _ in range(50):
        answered = await call("GET", asked.headers["location"])
        if answered.status_code != 202:
            break
        await asyncio.sleep(0.05)
    auth_token = AuthTokenAnswer.model_validate_json(answered.content)
    claims = AuthTokenClaims.model_validate(
        decode(auth_token.auth_token).claims
    )
    amount = claims.budget.amount if claims.budget else 0
    print(
        f"4. {answered.status_code}: an auth token from {claims.iss}"
        f" for {claims.aud}, ${amount / 100:,.2f}"
    )
    stored = await ps.store.select_mission(TENANT, mission.s256)
    assert stored is not None
    print(f"5. The trip has spent ${stored.spent / 100:,.2f} of its budget")


if __name__ == "__main__":
    asyncio.run(main())
