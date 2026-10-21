"""Claims, expectations, wire bodies and discovery: what a token or body must
be on its own, and every check a token that verified fails."""

import ast
from pathlib import Path

import httpx2 as httpx
import pytest
from pydantic import ValidationError

import introspection_aauth
from introspection_aauth.person_server.models import (
    Approval,
    ApprovalKind,
    MissionDocument,
    MissionGrant,
)
from introspection_aauth.protocol import (
    Discovery,
    SigningKey,
    VerificationError,
    httpsig,
    jwks,
    jwt,
)
from introspection_aauth.protocol.claims import (
    AgentExpectation,
    AgentTokenClaims,
    AuthGrant,
    AuthTokenClaims,
    Confirmation,
    DeliveryExpectation,
    PersonTokenClaims,
    PresentedExpectation,
    ResourceTokenClaims,
    ResourceTokenExpectation,
)
from introspection_aauth.protocol.discovery import is_identifier
from introspection_aauth.protocol.json import JsonObject
from introspection_aauth.protocol.keys import Jwk
from introspection_aauth.protocol.wire import TokenRequest

from .world import AS, PS, RESOURCE, World, forge, problem, usd

PACKAGE = Path(introspection_aauth.__file__).parent
TESTS = Path(__file__).parent
AGENT = SigningKey.generate()
OTHER = SigningKey.generate()


def test_no_module_uses_typing_any():
    """Bodies and claims are models; `JsonValue` is for arbitrary JSON."""
    found = []
    for path in [*PACKAGE.rglob("*.py"), *TESTS.rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "typing"
                and any(alias.name == "Any" for alias in node.names)
            ) or (
                isinstance(node, ast.Attribute)
                and node.attr == "Any"
                and isinstance(node.value, ast.Name)
                and node.value.id == "typing"
            ):
                found.append(f"{path.name}:{node.lineno}")
    assert found == []


def resource_claims(**update: str | None) -> ResourceTokenClaims:
    claims = ResourceTokenClaims(
        iss=RESOURCE,
        aud=AS,
        ps=PS,
        sub="person-1",
        agent_jkt=AGENT.kid,
        presented_jti="pt-1",
        mission_s256="m-1",
        tenant="acme",
        scope="book",
        budget=usd(60_000),
        iat=100,
        exp=400,
    )
    return claims.model_copy(update=update)


def auth_claims(grant: AuthGrant, *, iat: int = 100) -> AuthTokenClaims:
    return AuthTokenClaims.issue(
        grant,
        iss=AS,
        dwk="aauth-access.json",
        ps=PS,
        jwk=AGENT.public_jwk,
        jti="at-1",
        iat=iat,
        exp=iat + 300,
    )


def delivery(rt: ResourceTokenClaims) -> DeliveryExpectation:
    return DeliveryExpectation(
        issuer=AS,
        ps=PS,
        rt=rt,
        agent_jkt=AGENT.kid,
        not_after=500,
        sent=usd(60_000),
    )


def test_an_auth_token_for_exactly_the_call_passes():
    rt = resource_claims()
    assert (
        delivery(rt).failures(auth_claims(AuthGrant.requested(rt, "person-1")))
        == []
    )


@pytest.mark.parametrize(
    ("update", "names"),
    [
        ({"sub": "person-2"}, ["sub"]),
        ({"mission_s256": "m-2"}, ["mission_s256"]),
        ({"tenant": "other"}, ["tenant"]),
        ({"scope": "book cancel"}, ["scope"]),
        ({"aud": "https://elsewhere.example"}, ["aud"]),
        ({"budget": usd(70_000)}, ["budget"]),
        ({"budget": None}, ["budget"]),
        ({"sub": "person-2", "tenant": "other"}, ["sub", "tenant"]),
    ],
)
def test_each_failed_delivery_check_is_named(
    update: dict[str, str | None], names: list[str]
):
    rt = resource_claims()
    grant = AuthGrant.requested(rt, "person-1").model_copy(update=update)
    assert delivery(rt).failures(auth_claims(grant)) == names


def test_an_auth_token_from_elsewhere_bound_elsewhere_or_outliving_is_named():
    rt = resource_claims()
    grant = AuthGrant.requested(rt, "person-1")
    claims = auth_claims(grant, iat=300).model_copy(
        update={
            "iss": "https://other.example",
            "ps": "https://other-ps.example",
            "dwk": "aauth-person.json",
            "cnf": Confirmation(jwk=OTHER.public_jwk),
        }
    )
    assert delivery(rt).failures(claims) == ["dwk", "iss", "cnf", "ps", "exp"]


def test_resource_presented_and_agent_expectations_name_their_failures():
    rt = resource_claims(ps="https://other-ps.example", sub=None)
    assert ResourceTokenExpectation(
        ps=PS, aud=PS, agent_jkt=OTHER.kid, tenant="x", requires_presented=True
    ).failures(rt) == ["ps", "aud", "agent_jkt", "tenant", "sub"]
    presented = PersonTokenClaims(
        iss=PS,
        aud=RESOURCE,
        sub="person-1",
        cnf=Confirmation(jwk=AGENT.public_jwk),
        jti="pt-1",
        mission_s256="m-1",
        tenant="acme",
        iat=100,
        exp=400,
    )
    assert (
        PresentedExpectation(ps=PS, rt=resource_claims()).failures(presented)
        == []
    )
    assert PresentedExpectation(
        ps=AS, rt=resource_claims(tenant="x")
    ).failures(presented) == ["iss", "tenant"]
    agent = AgentTokenClaims(
        iss="https://agents.example",
        sub="aauth:a@agents.example",
        cnf=Confirmation(jwk=AGENT.public_jwk),
        ps="https://other-ps.example",
        iat=100,
        exp=400,
    )
    assert AgentExpectation(agent_jkt=OTHER.kid, ps=PS).failures(agent) == [
        "cnf",
        "ps",
    ]


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"iat": 200, "exp": 100}, "exp is not after iat"),
        ({"iat": 100, "exp": 100 + 7_200}, "too long a life"),
        ({"cnf": {"jwk": {"kty": "oct"}}}, "cnf"),
        ({"cnf": {}}, "cnf.jwk"),
        ({"sub": ""}, "sub"),
        ({"dwk": "aauth-person.json"}, "dwk"),
    ],
)
def test_malformed_agent_token_claims_do_not_verify(
    payload: JsonObject, detail: str
):
    key = SigningKey.generate()
    claims: JsonObject = {
        "iss": "https://agents.example",
        "dwk": "aauth-agent.json",
        "sub": "aauth:a@agents.example",
        "cnf": {"jwk": AGENT.public_jwk.model_dump(exclude_none=True)},
        "iat": 100,
        "exp": 400,
    } | payload
    token = forge(claims, key, jwt.AGENT_TOKEN)
    with pytest.raises(VerificationError) as refused:
        jwt.verify(token, jwks([key]), jwt.AGENT_TOKEN, 150, AgentTokenClaims)
    assert refused.value.code == "invalid_jwt"
    assert detail in refused.value.detail


def test_a_negative_budget_is_refused():
    with pytest.raises(ValidationError):
        TokenRequest.model_validate_json(
            b'{"resource_token":"r","agent_token":"a","presented_token":"p",'
            b'"budget":{"amount":-1,"unit":"USD","decimals":2}}'
        )


async def test_a_token_request_without_an_agent_token_is_invalid():
    world = World()
    url = f"{AS}/token"
    body = b'{"resource_token":"r","presented_token":"p"}'
    headers = world.ps.identity.signed("POST", url, body, world.now)
    refused = await world.http.post(url, content=body, headers=headers)
    assert refused.status_code == 400
    assert problem(refused).error == "invalid_request"
    assert refused.headers["content-type"] == "application/problem+json"


def test_a_stored_grant_of_any_shape_decodes():
    row = {
        "id": "a1",
        "kind": ApprovalKind.MISSION,
        "agent_id": "aauth:a@agents.example",
        "agent_jkt": AGENT.kid,
        "agent_jwk": AGENT.public_jwk.model_dump(exclude_none=True),
        "person": "sam",
        "description": "Book Sydney",
        "expires_at": 1,
        "created_at": 0,
    }
    mission = Approval.model_validate(
        row | {"grant": {"resources": [RESOURCE]}}
    )
    assert mission.grant == MissionGrant(resources=[RESOURCE])
    assert Approval.model_validate(row | {"grant": {}}).grant == MissionGrant()
    assert Approval.model_validate(row).grant == MissionGrant()
    auth = Approval.model_validate(
        row
        | {
            "grant": {
                "aud": RESOURCE,
                "sub": "person-1",
                "scope": "book",
                "budget": {"amount": 1, "unit": "USD", "decimals": 2},
                "mission_s256": "m-1",
                "tenant": "acme",
            }
        }
    )
    assert isinstance(auth.grant, AuthGrant) and auth.grant.budget == usd(1)


def test_the_mission_blob_is_raw_utf8_and_names_no_person():
    blob = MissionDocument(
        agent="aauth:a@agents.example",
        approval="a1",
        approved_at="2026-10-21T00:00:00Z",
        expires_at="2026-10-22T00:00:00Z",
        description="Sam to Zürich, ≤ $2,000",
        approved_resources=[RESOURCE],
        budget=usd(200_000),
    ).to_json()
    assert "Zürich, ≤" in blob and "\\u" not in blob
    assert '"person"' not in blob and '"approval":"a1"' in blob


@pytest.mark.parametrize(
    "issuer",
    [
        "http://agents.example",
        "https://agents.example/",
        "https://agents.example:8443",
        "https://agents.example/path",
        "https://user@agents.example",
        "https://agents.example?x=1",
        "https://agents.example#f",
        "https://Agents.example",
        "agents.example",
    ],
)
async def test_a_malformed_issuer_is_refused_unfetched(issuer: str):
    fetched: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return httpx.Response(404)

    discovery = Discovery(
        httpx.AsyncClient(transport=httpx.MockTransport(answer))
    )
    assert not is_identifier(issuer)
    with pytest.raises(VerificationError) as refused:
        await discovery.metadata(issuer, "aauth-agent.json")
    assert refused.value.code == "invalid_issuer" and fetched == []


async def test_an_http_jwks_uri_is_refused_and_a_redirect_not_followed():
    issuer = "https://agents.example"
    documents = {
        f"{issuer}/.well-known/aauth-agent.json": httpx.Response(
            200,
            json={"issuer": issuer, "jwks_uri": "http://agents.example/jwks"},
        ),
        f"{issuer}/.well-known/aauth-person.json": httpx.Response(
            302, headers={"Location": f"{issuer}/elsewhere.json"}
        ),
        f"{issuer}/elsewhere.json": httpx.Response(
            200, json={"issuer": issuer, "jwks_uri": f"{issuer}/jwks"}
        ),
    }
    fetched: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return documents[str(request.url)]

    discovery = Discovery(
        httpx.AsyncClient(
            transport=httpx.MockTransport(answer), follow_redirects=True
        )
    )
    with pytest.raises(VerificationError) as http_keys:
        await discovery.metadata(issuer, "aauth-agent.json")
    assert http_keys.value.code == "invalid_metadata"
    with pytest.raises(VerificationError):
        await discovery.metadata(issuer, "aauth-person.json")
    assert f"{issuer}/elsewhere.json" not in fetched


async def test_an_authorization_header_must_be_signed_when_present():
    url = "https://ps.example/aauth/mission"
    token = jwt.encode(
        AgentTokenClaims(
            iss="https://agents.example",
            sub="aauth:a@agents.example",
            cnf=Confirmation(jwk=AGENT.public_jwk),
            iat=1,
            exp=200,
        ),
        AGENT,
        jwt.AGENT_TOKEN,
    )
    covered = httpsig.sign(
        AGENT,
        httpsig.jwt_key(token),
        "GET",
        url,
        authorization="AAuth abc",
        created=100,
    )
    verified = await httpsig.verify(
        httpsig.SignedRequest("GET", url, covered), 100
    )
    assert verified.thumbprint == AGENT.kid
    uncovered = httpsig.sign(
        AGENT, httpsig.jwt_key(token), "GET", url, created=100
    )
    with pytest.raises(VerificationError) as refused:
        await httpsig.verify(
            httpsig.SignedRequest(
                "GET", url, uncovered | {"Authorization": "AAuth abc"}
            ),
            100,
        )
    assert refused.value.detail == "authorization must be covered"


def test_a_jwk_needs_a_key_type():
    with pytest.raises(ValidationError):
        Jwk.model_validate({"crv": "Ed25519"})
