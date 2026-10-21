"""The shared protocol layer: RFC 9421 against the spec author's library and
the data plane's current verifier, tokens, keys and discovery."""

import base64
import json
import time
from pathlib import Path

import http_sfv
import httpx2 as httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
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
    AgentTokenClaims,
    Claims,
    Confirmation,
    PersonTokenClaims,
)
from introspection_aauth.protocol.keys import (
    Jwk,
    b64url,
    b64url_decode,
    thumbprint,
    verify,
)

from .world import forge

VECTORS = json.loads(
    (Path(__file__).parent / "vectors" / "hellocoop.json").read_text()
)


def vector_key() -> SigningKey:
    return SigningKey.from_seed(b64url_decode(VECTORS["seed"]))


def test_what_this_package_signs_is_what_hellocoop_verified():
    for case in VECTORS["signed_here_verified_by_hellocoop"]:
        signed = httpsig.sign(
            vector_key(),
            httpsig.jwt_key(VECTORS["jwt"]),
            case["method"],
            case["url"],
            body=case["body"].encode() if case["body"] else None,
            content_type=case.get("content_type") or "application/json",
            created=VECTORS["created"],
        )
        assert signed == case["headers"], case["url"]


async def test_what_hellocoop_signed_verifies_here():
    for case in VECTORS["signed_by_hellocoop"]:
        request = httpsig.SignedRequest(
            case["method"],
            case["url"],
            case["headers"],
            case["body"].encode() if case["body"] else None,
        )
        verified = await httpsig.verify(request, VECTORS["created"])
        assert verified.thumbprint == vector_key().kid
        assert verified.token == VECTORS["jwt"]


def test_what_this_package_signs_verifies_under_the_data_planes_verifier():
    """The data plane verifies with aauth-signing, converting the Signature
    header to the base64url that 0.2.0 reads."""
    from aauth_signing import verify_signature
    from aauth_signing.tokens.common import verify_agent_claims, verify_jwt

    provider, agent = SigningKey.generate(), SigningKey.generate()
    now = int(time.time())
    token = jwt.encode(
        AgentTokenClaims(
            dwk=AGENT_DWK,
            iss="https://agents.example",
            sub="aauth:travel@agents.example",
            jti="a1",
            iat=now,
            exp=now + 600,
            cnf=Confirmation(jwk=agent.public_jwk),
        ),
        provider,
        jwt.AGENT_TOKEN,
    )
    body = b'{"description":"Sydney"}'
    url = "https://ps.example/aauth/mission"
    headers = httpsig.sign(
        agent, httpsig.jwt_key(token), "POST", url, body=body, created=now
    )
    keys = jwks([provider]).model_dump(exclude_none=True)
    assert (
        verify_agent_claims(token, lambda *_: keys)["sub"]
        == "aauth:travel@agents.example"
    )
    signatures = http_sfv.Dictionary()
    signatures.parse(headers["signature"].encode())
    as_library_reads = ", ".join(
        f"{label}=:{b64url(item.value)}:" for label, item in signatures.items()
    )
    assert verify_signature(
        "POST",
        url,
        headers,
        body,
        headers["signature-input"],
        as_library_reads,
        headers["signature-key"],
        jwks_fetcher=lambda *_: keys,
        required_components=[
            "@method",
            "@authority",
            "@path",
            "signature-key",
            "content-digest",
        ],
    )
    issued = jwt.encode(
        Claims(iss="https://ps.example", jti="c1", iat=now, exp=now + 60),
        provider,
        jwt.PERSON_TOKEN,
    )
    assert verify_jwt(issued, keys)["iss"] == "https://ps.example"


async def test_a_tampered_or_stale_request_does_not_verify():
    key = SigningKey.generate()
    token = jwt.encode(
        AgentTokenClaims(
            dwk=AGENT_DWK,
            jti="agent-x",
            iss="https://agents.example",
            sub="aauth:a@agents.example",
            cnf=Confirmation(jwk=key.public_jwk),
            iat=1,
            exp=2,
        ),
        key,
        jwt.AGENT_TOKEN,
    )
    headers = httpsig.sign(
        key,
        httpsig.jwt_key(token),
        "POST",
        "https://ps.example/x",
        body=b"{}",
        created=100,
    )
    tampered = httpsig.SignedRequest(
        "POST", "https://ps.example/x", headers, b'{"a":1}'
    )
    with pytest.raises(VerificationError) as digest:
        await httpsig.verify(tampered, 100)
    assert digest.value.code == "invalid_input"
    stale = httpsig.SignedRequest(
        "POST", "https://ps.example/x", headers, b"{}"
    )
    with pytest.raises(VerificationError) as late:
        await httpsig.verify(stale, 1_000)
    assert late.value.code == "invalid_signature"
    moved = httpsig.SignedRequest(
        "POST", "https://other.example/x", headers, b"{}"
    )
    with pytest.raises(VerificationError):
        await httpsig.verify(moved, 100)


async def test_a_server_signature_resolves_its_published_key():
    server = SigningKey.generate()
    headers = httpsig.sign(
        server,
        httpsig.jwks_uri_key(
            "https://ps.example", "aauth-person.json", server.kid
        ),
        "GET",
        "https://as.example/pending/1",
        created=100,
    )
    assert (
        httpsig.named_server(headers["signature-key"]) == "https://ps.example"
    )

    async def resolve(issuer: str, dwk: str, kid: str) -> Jwk:
        assert (issuer, dwk, kid) == (
            "https://ps.example",
            "aauth-person.json",
            server.kid,
        )
        return server.public_jwk

    request = httpsig.SignedRequest(
        "GET", "https://as.example/pending/1", headers
    )
    verified = await httpsig.verify(request, 100, resolve)
    assert (
        verified.scheme == "jwks_uri"
        and verified.server == "https://ps.example"
    )


def test_tokens_verify_only_as_issued():
    key = SigningKey.generate()
    token = jwt.encode(
        Claims(iss="https://ps.example", jti="c1", iat=100, exp=200),
        key,
        jwt.AUTH_TOKEN,
    )
    assert (
        jwt.verify(token, jwks([key]), jwt.AUTH_TOKEN, 150, Claims).exp == 200
    )
    for typ, now, code in (
        (jwt.PERSON_TOKEN, 150, "invalid_jwt"),
        (jwt.AUTH_TOKEN, 250, "expired_jwt"),
        (jwt.AUTH_TOKEN, 0, "clock_skew"),
    ):
        with pytest.raises(VerificationError) as failed:
            jwt.verify(token, jwks([key]), typ, now, Claims)
        assert failed.value.code == code
    with pytest.raises(VerificationError) as other_key:
        jwt.verify(
            token, jwks([SigningKey.generate()]), jwt.AUTH_TOKEN, 150, Claims
        )
    assert other_key.value.code == "unknown_key"
    long = forge(
        {"iss": "https://ps.example", "jti": "c1", "iat": 100, "exp": 7_300},
        key,
        jwt.AUTH_TOKEN,
    )
    assert jwt.verify(long, jwks([key]), jwt.AUTH_TOKEN, 150, Claims)
    with pytest.raises(VerificationError) as too_long:
        jwt.verify(long, jwks([key]), jwt.AUTH_TOKEN, 150, PersonTokenClaims)
    assert too_long.value.code == "invalid_jwt"


def test_a_previous_key_still_verifies_what_it_signed():
    old, new = SigningKey.generate(), SigningKey.generate()
    token = jwt.encode(
        Claims(iss="https://ps.example", jti="c1", iat=1, exp=10),
        old,
        jwt.PERSON_TOKEN,
    )
    assert jwt.verify(token, jwks([new, old]), jwt.PERSON_TOKEN, 5, Claims)


def test_es256_keys_verify():
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    jwk = Jwk(
        kty="EC",
        crv="P-256",
        alg="ES256",
        x=b64url(numbers.x.to_bytes(32, "big")),
        y=b64url(numbers.y.to_bytes(32, "big")),
    )
    r, s = decode_dss_signature(
        private.sign(b"data", ec.ECDSA(hashes.SHA256()))
    )
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    assert verify(jwk, b"data", signature)
    assert not verify(jwk, b"other", signature)
    assert thumbprint(jwk) == thumbprint(
        jwk.model_copy(update={"alg": None, "kid": "x"})
    )


def test_a_key_loads_from_pem():
    key = SigningKey.generate()
    pem = key._private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    assert SigningKey.from_pem(pem).kid == key.kid
    assert base64.urlsafe_b64decode(f"{key.public_jwk.x}=")


async def test_discovery_caches_keys_and_refetches_a_failing_set_sparingly():
    fetched: list[str] = []
    issuer = "https://agents.example"

    def answer(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if request.url.path.endswith("aauth-agent.json"):
            return httpx.Response(
                200, json={"issuer": issuer, "jwks_uri": f"{issuer}/jwks"}
            )
        return httpx.Response(200, json={"keys": []})

    clock = [0.0]
    discovery = Discovery(
        httpx.AsyncClient(transport=httpx.MockTransport(answer)),
        clock=lambda: clock[0],
    )
    await discovery.jwks(issuer, "aauth-agent.json")
    await discovery.jwks(issuer, "aauth-agent.json")
    assert len(fetched) == 2
    await discovery.jwks(issuer, "aauth-agent.json", refresh=True)
    assert len(fetched) == 2
    clock[0] = 31
    await discovery.jwks(issuer, "aauth-agent.json", refresh=True)
    assert len(fetched) == 4
    with pytest.raises(VerificationError):
        await discovery.key(issuer, "aauth-agent.json", "missing")
