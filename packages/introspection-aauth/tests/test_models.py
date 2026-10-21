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
    AGENT_DWK,
    PERSON_DWK,
    RESOURCE_DWK,
    AgentExpectation,
    AgentTokenClaims,
    AuthGrant,
    AuthTokenClaims,
    Claims,
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


TYPING = {"typing", "typing_extensions"}
BARE = {"dict", "list", "Dict", "List"}


def _annotations(tree: ast.AST) -> list[ast.expr]:
    """Every annotation, with string annotations parsed."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            found.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
    parsed: list[ast.expr] = []
    for annotation in found:
        parsed.append(annotation)
        for n in ast.walk(annotation):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                try:
                    parsed.append(ast.parse(n.value, mode="eval").body)
                except SyntaxError:
                    pass
    return parsed


def _untyped(tree: ast.AST) -> list[int]:
    """Lines that type something as `Any` or `object`, or as a bare
    `dict` or `list`."""
    found: list[int] = []
    typing_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            typing_names |= {
                a.asname or a.name for a in node.names if a.name in TYPING
            }
        elif isinstance(node, ast.ImportFrom) and node.module in TYPING:
            found += [node.lineno for a in node.names if a.name == "Any"]
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "Any"
            and isinstance(node.value, ast.Name)
            and node.value.id in typing_names
        ):
            found.append(node.lineno)
        elif isinstance(node, ast.Subscript) and any(
            isinstance(n, ast.Name) and n.id in {"object", "Any"}
            for n in ast.walk(node.slice)
        ):
            found.append(node.lineno)
    for annotation in _annotations(tree):
        subscripted = {
            id(n.value)
            for n in ast.walk(annotation)
            if isinstance(n, ast.Subscript)
        }
        for n in ast.walk(annotation):
            if isinstance(n, ast.Name) and (
                n.id in {"object", "Any"}
                or (n.id in BARE and id(n) not in subscripted)
            ):
                found.append(getattr(annotation, "lineno", 0))
    return found


def test_no_module_types_anything_as_any_or_object():
    """Bodies and claims are models; `JsonValue` is for arbitrary JSON."""
    found = [
        f"{path.name}:{line}"
        for path in [*PACKAGE.rglob("*.py"), *TESTS.rglob("*.py")]
        for line in _untyped(ast.parse(path.read_text()))
    ]
    assert found == []


@pytest.mark.parametrize(
    "source",
    [
        "import typing as t\nx: t.Any",
        "from typing_extensions import Any",
        "def f(x: 'object') -> None: ...",
        "def f() -> 'Any': ...",
        "Alias = dict[str, object]",
        "def f(x: dict) -> None: ...",
        "def f() -> dict[str, list]: ...",
    ],
)
def test_the_guard_finds_each_way_of_writing_an_untyped_type(source: str):
    assert _untyped(ast.parse(source))


def resource_claims(**update: str | None) -> ResourceTokenClaims:
    claims = ResourceTokenClaims(
        dwk=RESOURCE_DWK,
        jti="rt-1",
        iss=RESOURCE,
        aud=AS,
        ps=PS,
        sub="person-1",
        agent_jkt=AGENT.kid,
        presented_jti="pt-1",
        mission_s256="m-1",
        tenant="acme",
        account="acct-1",
        r3_uri=f"{RESOURCE}/r3/1",
        r3_s256="h-1",
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


def test_a_trailing_slash_on_the_resource_is_the_same_audience():
    rt = resource_claims()
    grant = AuthGrant.requested(rt, "person-1")
    claims = auth_claims(grant).model_copy(update={"aud": f"{RESOURCE}/"})
    assert delivery(rt).failures(claims) == []


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
        ({"account": "acct-2"}, ["account"]),
        ({"r3_uri": f"{RESOURCE}/r3/2"}, ["r3_uri"]),
        ({"r3_s256": "other"}, ["r3_s256"]),
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


def presented_claims(**update: str) -> PersonTokenClaims:
    claims = PersonTokenClaims(
        dwk=PERSON_DWK,
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
    return claims.model_copy(update=update)


@pytest.mark.parametrize(
    ("update", "name"),
    [
        ({"iss": AS}, "iss"),
        ({"aud": "https://elsewhere.example"}, "aud"),
        ({"jti": "pt-2"}, "jti"),
        ({"sub": "person-2"}, "sub"),
        ({"mission_s256": "m-2"}, "mission_s256"),
        ({"tenant": "other"}, "tenant"),
    ],
)
def test_each_failed_presented_check_is_named(
    update: dict[str, str], name: str
):
    expectation = PresentedExpectation(ps=PS, rt=resource_claims())
    assert expectation.failures(presented_claims()) == []
    assert expectation.failures(presented_claims(**update)) == [name]


def test_a_presented_token_bound_to_another_key_is_named():
    presented = presented_claims().model_copy(
        update={"cnf": Confirmation(jwk=OTHER.public_jwk)}
    )
    assert PresentedExpectation(ps=PS, rt=resource_claims()).failures(
        presented
    ) == ["cnf"]


@pytest.mark.parametrize(
    ("absent", "name"),
    [
        ("sub", "sub"),
        ("presented_jti", "presented_jti"),
        ("agent_jkt", "agent_jkt_present"),
    ],
)
def test_a_resource_token_missing_what_a_presented_call_needs_is_named(
    absent: str, name: str
):
    expectation = ResourceTokenExpectation(ps=PS, requires_presented=True)
    assert expectation.failures(resource_claims()) == []
    assert expectation.failures(resource_claims(**{absent: None})) == [name]


def test_resource_presented_and_agent_expectations_name_their_failures():
    rt = resource_claims(ps="https://other-ps.example", sub=None)
    assert ResourceTokenExpectation(
        ps=PS, aud=PS, agent_jkt=OTHER.kid, tenant="x", requires_presented=True
    ).failures(rt) == ["ps", "aud", "agent_jkt", "tenant", "sub"]
    presented = PersonTokenClaims(
        dwk=PERSON_DWK,
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
        dwk=AGENT_DWK,
        jti="agent-x",
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
        ({"iat": 100, "exp": 100 + 86_401}, "lifetime is over 86400"),
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
        "jti": "agent-1",
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
        "agent_expires_at": 1,
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
            dwk=AGENT_DWK,
            jti="agent-x",
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


def lifetime_claims(seconds: int) -> JsonObject:
    return {
        "iss": "https://ps.example",
        "dwk": "aauth-person.json",
        "aud": RESOURCE,
        "sub": "person-1",
        "cnf": {"jwk": AGENT.public_jwk.model_dump(exclude_none=True)},
        "jti": "t-1",
        "iat": 100,
        "exp": 100 + seconds,
    }


@pytest.mark.parametrize(
    ("model", "dwk", "seconds", "allowed"),
    [
        (AgentTokenClaims, "aauth-agent.json", 2 * 3_600, True),
        (AgentTokenClaims, "aauth-agent.json", 24 * 3_600, True),
        (AgentTokenClaims, "aauth-agent.json", 24 * 3_600 + 1, False),
        (PersonTokenClaims, "aauth-person.json", 3_600, True),
        (PersonTokenClaims, "aauth-person.json", 3_601, False),
        (AuthTokenClaims, "aauth-access.json", 3_601, False),
        (ResourceTokenClaims, "aauth-resource.json", 3_600, True),
    ],
)
def test_each_token_type_caps_its_own_lifetime(
    model: type[Claims], dwk: str, seconds: int, allowed: bool
):
    claims = lifetime_claims(seconds) | {"dwk": dwk, "ps": PS}
    if allowed:
        assert model.model_validate(claims).exp == 100 + seconds
    else:
        with pytest.raises(ValidationError, match="lifetime is over"):
            model.model_validate(claims)


@pytest.mark.parametrize("missing", ["dwk", "jti"])
def test_a_token_without_its_dwk_or_jti_is_malformed(missing: str):
    claims = lifetime_claims(60)
    del claims[missing]
    with pytest.raises(ValidationError):
        PersonTokenClaims.model_validate(claims)
