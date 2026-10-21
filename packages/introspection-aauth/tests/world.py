"""Every party of AAuth -11, in process: an agent provider, a resource, a
Person Server and an Access Server behind their FastAPI routers, and an agent.
One transport stands in for the internet, routing each origin to its party."""

import json
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx
from fastapi import FastAPI

from introspection_aauth.access_server import AccessServer, Verdict
from introspection_aauth.access_server import MemoryStore as AccessStore
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

AP = "https://agents.example"
RESOURCE = "https://booking.example"
PS = "https://ps.example"
AS = "https://as.booking.example"
TENANT = "acme"
T0 = 1_791_000_000
USD = {"unit": "USD", "decimals": 2}


def usd(amount: int) -> Budget:
    return Budget(amount=amount, unit="USD", decimals=2)


class Net(httpx.AsyncBaseTransport):
    """Routes a request by its origin: to an app, or to a fixed document."""

    def __init__(self) -> None:
        self.apps: dict[str, httpx.ASGITransport] = {}
        self.documents: dict[str, Any] = {}
        self.calls: list[str] = []
        #: How many more times a request to each URL fails to connect.
        self.failures: dict[str, int] = {}

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        url = str(request.url)
        self.calls.append(f"{request.method} {url}")
        if self.failures.get(url, 0) > 0:
            self.failures[url] -= 1
            raise httpx.ConnectError("connection refused", request=request)
        if url in self.documents:
            document = self.documents[url]
            if isinstance(document, bytes):
                return httpx.Response(200, content=document)
            return httpx.Response(200, json=document)
        origin = f"{request.url.scheme}://{request.url.host}"
        if origin in self.apps:
            return await self.apps[origin].handle_async_request(request)
        return httpx.Response(404, json={"error": "not_found"})


class World:
    def __init__(
        self, policy: Any = None, ps_store: MemoryStore | None = None
    ) -> None:
        self.now = T0
        self.net = Net()
        self.http = httpx.AsyncClient(transport=self.net)
        self.ap_key, self.resource_key, self.agent_key = (
            SigningKey.generate() for _ in range(3)
        )
        self.net.documents |= {
            f"{AP}/.well-known/aauth-agent.json": {
                "issuer": AP,
                "jwks_uri": f"{AP}/jwks.json",
            },
            f"{AP}/jwks.json": jwks([self.ap_key]),
            f"{RESOURCE}/.well-known/aauth-resource.json": {
                "issuer": RESOURCE,
                "jwks_uri": f"{RESOURCE}/jwks.json",
            },
            f"{RESOURCE}/jwks.json": jwks([self.resource_key]),
        }
        self.ps_store = ps_store or MemoryStore()
        self.ps = PersonServer(
            PS,
            SigningKey.generate(),
            self.ps_store,
            subject_secret=b"test-subject-secret",
            agent_providers=[AP],
            http=self.http,
            endpoint_base=f"{PS}/aauth",
            default_tenant=TENANT,
            clock=lambda: self.now,
        )
        self.policy = policy or (lambda request: Verdict.allow())
        self.access_store = AccessStore()
        self.access = AccessServer(
            AS,
            SigningKey.generate(),
            lambda request: self.policy(request),
            resources=[RESOURCE],
            person_servers=[PS],
            agent_providers=[AP],
            http=self.http,
            store=self.access_store,
            clock=lambda: self.now,
        )
        for origin, router in (
            (PS, person_server_router(self.ps)),
            (AS, access_server_router(self.access)),
        ):
            app = FastAPI()
            app.include_router(router)
            self.net.apps[origin] = httpx.ASGITransport(app=app)
        self.agent_token = encode(
            {
                "iss": AP,
                "dwk": "aauth-agent.json",
                "sub": "aauth:travel@agents.example",
                "jti": "agent-1",
                "iat": T0,
                "exp": T0 + 3_600,
                "cnf": {"jwk": self.agent_key.public_jwk},
            },
            self.ap_key,
            AGENT_TOKEN,
        )

    async def call(
        self, method: str, url: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        """A request the agent signs (`sig=jwt`, its agent token)."""
        content = json.dumps(body).encode() if body is not None else None
        headers = sign(
            self.agent_key,
            jwt_key(self.agent_token),
            method,
            url,
            body=content,
            created=self.now,
        )
        return await self.http.request(
            method, url, content=content, headers=headers
        )

    async def follow(self, response: httpx.Response) -> httpx.Response:
        assert response.status_code == 202, response.text
        return await self.call("GET", response.headers["location"])

    async def approved_mission(self, budget: int) -> dict[str, Any]:
        proposed = await self.call(
            "POST",
            f"{PS}/aauth/mission",
            {
                "description": "Book Sydney",
                "resources": [RESOURCE],
                "login_hint": "sam",
            },
        )
        approval_id = urlsplit(proposed.headers["location"]).path.rsplit(
            "/", 1
        )[1]
        await self.ps.decide(
            TENANT,
            approval_id,
            ApprovalStatus.APPROVED,
            decided_by="dana",
            budget=usd(budget),
        )
        done = await self.follow(proposed)
        assert done.status_code == 200, done.text
        return done.json()

    def resource_token(
        self, mission: dict[str, Any], amount: int | None, aud: str = PS
    ) -> tuple[str, str]:
        """A resource token for a call costing `amount`, and the person token it answers."""
        person_token = mission["person_tokens"][RESOURCE]
        presented = decode(person_token).claims
        token = encode(
            {
                "iss": RESOURCE,
                "dwk": "aauth-resource.json",
                "aud": aud,
                "ps": PS,
                "agent_jkt": self.agent_key.kid,
                "presented_jti": presented["jti"],
                "sub": presented["sub"],
                "mission_s256": mission["s256"],
                "tenant": TENANT,
                "scope": "book",
                "iat": self.now,
                "exp": self.now + 300,
                **(
                    {"budget": {"amount": amount, **USD}}
                    if amount is not None
                    else {}
                ),
            },
            self.resource_key,
            RESOURCE_TOKEN,
        )
        return token, person_token

    async def ask(
        self, mission: dict[str, Any], amount: int | None, aud: str = PS
    ) -> httpx.Response:
        token, person_token = self.resource_token(mission, amount, aud)
        return await self.call(
            "POST",
            f"{PS}/aauth/token",
            {"resource_token": token, "presented_token": person_token},
        )

    async def spent(self, s256: str) -> int:
        mission = await self.ps_store.mission(TENANT, s256)
        assert mission is not None
        return mission.spent
