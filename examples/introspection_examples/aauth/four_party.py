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
        uv run --with uvicorn uvicorn introspection_examples.aauth.four_party:person_server_app --port 8001
    ACCESS_SERVER=https://as.example RESOURCE=https://booking.example \\
        PERSON_SERVER=https://ps.example AGENT_PROVIDER=https://agents.example \\
        uv run --with uvicorn uvicorn introspection_examples.aauth.four_party:access_server_app --port 8002
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

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
from introspection_aauth.protocol import Budget, SigningKey, jwks
from introspection_aauth.protocol.httpsig import jwt_key, sign
from introspection_aauth.protocol.jwt import (
    AGENT_TOKEN,
    RESOURCE_TOKEN,
    decode,
    encode,
)

AP = os.environ.get("AGENT_PROVIDER", "https://agents.example")
PS = os.environ.get("PERSON_SERVER", "https://ps.example")
AS = os.environ.get("ACCESS_SERVER", "https://as.flightsector.example")
RESOURCE = os.environ.get("RESOURCE", "https://booking.flightsector.example")
TENANT = "acme"
USD = {"unit": "USD", "decimals": 2}


# #region docs:aauth-servers
def flight_sector(request: AccessRequest) -> Verdict:
    """The airline's policy: it books only for companies with an account."""
    if (request.tenant, request.ps) == (TENANT, PS):
        return Verdict.allow()
    return Verdict.deny("no Flight Sector account")


def servers(http: httpx.AsyncClient) -> tuple[PersonServer, AccessServer]:
    person_server = PersonServer(
        PS,
        SigningKey.generate(),
        MemoryStore(),
        subject_secret=os.urandom(32),
        agent_providers=[AP],
        http=http,
        endpoint_base=f"{PS}/aauth",
        default_tenant=TENANT,
    )
    access_server = AccessServer(
        AS,
        SigningKey.generate(),
        flight_sector,
        resources=[RESOURCE],
        person_servers=[PS],
        agent_providers=[AP],
        http=http,
    )
    return person_server, access_server


def app(router: Any) -> FastAPI:
    served = FastAPI()
    served.include_router(router)
    return served


# #endregion docs:aauth-servers

_http = httpx.AsyncClient()
_person_server, _access_server = servers(_http)
person_server_app = app(person_server_router(_person_server))
access_server_app = app(access_server_router(_access_server))


class Internet(httpx.AsyncBaseTransport):
    """Routes each origin to its party, in this process."""

    def __init__(self) -> None:
        self.parties: dict[str, httpx.AsyncBaseTransport] = {}
        self.documents: dict[str, Any] = {}

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        if str(request.url) in self.documents:
            return httpx.Response(200, json=self.documents[str(request.url)])
        origin = f"{request.url.scheme}://{request.url.host}"
        print(f"  → {request.method} {request.url}")
        return await self.parties[origin].handle_async_request(request)


async def main() -> None:
    internet = Internet()
    http = httpx.AsyncClient(transport=internet)
    person_server, access_server = servers(http)
    internet.parties[PS] = httpx.ASGITransport(
        app=app(person_server_router(person_server))
    )
    internet.parties[AS] = httpx.ASGITransport(
        app=app(access_server_router(access_server))
    )

    # The agent provider and the airline's booking API, as fixed documents.
    provider, airline, agent = (SigningKey.generate() for _ in range(3))
    internet.documents |= {
        f"{AP}/.well-known/aauth-agent.json": {
            "issuer": AP,
            "jwks_uri": f"{AP}/jwks.json",
        },
        f"{AP}/jwks.json": jwks([provider]),
        f"{RESOURCE}/.well-known/aauth-resource.json": {
            "issuer": RESOURCE,
            "jwks_uri": f"{RESOURCE}/jwks.json",
        },
        f"{RESOURCE}/jwks.json": jwks([airline]),
    }
    now = person_server.clock()
    agent_token = encode(
        {
            "iss": AP,
            "dwk": "aauth-agent.json",
            "sub": "aauth:travel@agents.example",
            "jti": "agent-1",
            "iat": now,
            "exp": now + 3_600,
            "cnf": {"jwk": agent.public_jwk},
        },
        provider,
        AGENT_TOKEN,
    )

    async def call(
        method: str, url: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        content = json.dumps(body).encode() if body is not None else None
        headers = sign(
            agent,
            jwt_key(agent_token),
            method,
            url,
            body=content,
            created=person_server.clock(),
        )
        return await http.request(
            method, url, content=content, headers=headers
        )

    print("1. The agent proposes the trip")
    proposed = await call(
        "POST",
        f"{PS}/aauth/mission",
        {
            "description": "Sam to Sydney, up to $2,000",
            "resources": [RESOURCE],
            "login_hint": "sam@acme.example",
        },
    )
    print(f"   {proposed.status_code}: it waits on Sam's manager")
    approval_id = proposed.headers["location"].rsplit("/", 1)[1]
    await person_server.decide(
        TENANT,
        approval_id,
        ApprovalStatus.APPROVED,
        decided_by="dana@acme.example",
        budget=Budget(amount=200_000, **USD),
    )
    mission = (await call("GET", proposed.headers["location"])).json()
    print("2. Dana approves it with a $2,000 budget; the agent collects it")

    person_token = mission["person_tokens"][RESOURCE]
    presented = decode(person_token).claims
    resource_token = encode(
        {
            "iss": RESOURCE,
            "dwk": "aauth-resource.json",
            "aud": AS,
            "ps": PS,
            "agent_jkt": agent.kid,
            "presented_jti": presented["jti"],
            "sub": presented["sub"],
            "mission_s256": mission["s256"],
            "tenant": TENANT,
            "scope": "book",
            "budget": {"amount": 145_000, **USD},
            "iat": now,
            "exp": now + 300,
        },
        airline,
        RESOURCE_TOKEN,
    )
    print("3. The airline quotes $1,450 and asks for an auth token")
    asked = await call(
        "POST",
        f"{PS}/aauth/token",
        {"resource_token": resource_token, "presented_token": person_token},
    )
    print(f"   {asked.status_code}: within budget, so off to the airline's AS")
    for _ in range(50):
        answered = await call("GET", asked.headers["location"])
        if answered.status_code != 202:
            break
        await asyncio.sleep(0.05)
    claims = decode(answered.json()["auth_token"]).claims
    print(
        f"4. {answered.status_code}: an auth token from {claims['iss']}"
        f" for {claims['aud']}, ${claims['budget']['amount'] / 100:,.2f}"
    )
    stored = await person_server.store.mission(TENANT, mission["s256"])
    assert stored is not None
    print(f"5. The trip has spent ${stored.spent / 100:,.2f} of its budget")


if __name__ == "__main__":
    asyncio.run(main())
