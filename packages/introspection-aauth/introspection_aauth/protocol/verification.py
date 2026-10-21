"""Verifying what a server is presented: an agent's or a server's signed
request, and the agent and resource tokens it carries."""

from typing import TypeVar

from introspection_aauth.protocol import httpsig, jwt
from introspection_aauth.protocol.claims import (
    AGENT_DWK,
    RESOURCE_DWK,
    AgentTokenClaims,
    Claims,
    ResourceTokenClaims,
)
from introspection_aauth.protocol.discovery import Discovery
from introspection_aauth.protocol.errors import (
    InvalidToken,
    Unauthorized,
    VerificationError,
)
from introspection_aauth.protocol.expectations import (
    ResourceTokenExpectation,
)
from introspection_aauth.protocol.keys import Jwk
from introspection_aauth.protocol.models import Agent

ClaimsModel = TypeVar("ClaimsModel", bound=Claims)


#: How a `401` names the scheme an agent should sign with.
ACCEPT_JWT_SCHEME = {"Accept-Signature-Scheme": "jwt"}


async def verify_resource_token(
    token: str,
    discovery: Discovery,
    resource: str,
    now: int,
    expectation: ResourceTokenExpectation,
) -> ResourceTokenClaims:
    """A resource token, against its resource's keys (`#resource-token`),
    and what it must say for this server; `400 invalid_resource_token`
    otherwise."""
    try:
        rt = await discovery.verified(
            resource,
            RESOURCE_DWK,
            lambda keys: jwt.verify(
                token, keys, jwt.RESOURCE_TOKEN, now, ResourceTokenClaims
            ),
        )
    except VerificationError as exc:
        raise InvalidToken(
            "resource", f"does not verify: {exc.detail}"
        ) from None
    wrong = expectation.failures(rt)
    if wrong:
        raise InvalidToken(
            "resource", f"its {', '.join(wrong)} not this request's"
        )
    return rt


async def verify_agent_token(
    token: str, discovery: Discovery, providers: set[str], now: int
) -> AgentTokenClaims:
    """An agent token from a trusted agent provider (`#agent-token`)."""
    _, unverified = jwt.peek(token)
    provider = (unverified.iss or "").rstrip("/")
    if provider not in providers:
        raise VerificationError(
            "invalid_jwt", "its agent provider is not trusted here"
        )
    return await discovery.verified(
        provider,
        AGENT_DWK,
        lambda keys: jwt.verify(
            token, keys, jwt.AGENT_TOKEN, now, AgentTokenClaims
        ),
    )


async def verify_agent(
    request: httpsig.SignedRequest,
    discovery: Discovery,
    providers: set[str],
    now: int,
) -> Agent:
    """An agent's signed request (`sig=jwt`, its agent token), or a `401`.
    Any other scheme is refused before anything is read or fetched."""
    try:
        scheme = httpsig.signature_scheme(
            request.headers.get("signature-key", "")
        )
        if scheme != "jwt":
            raise VerificationError("unsupported_scheme", "sign with sig=jwt")
        verified = await httpsig.verify(request, now)
        if verified.scheme != "jwt" or verified.token is None:
            raise VerificationError("unsupported_scheme", "sign with sig=jwt")
        claims = await verify_agent_token(
            verified.token, discovery, providers, now
        )
        if claims.cnf.thumbprint != verified.thumbprint:
            raise VerificationError(
                "invalid_signature", "not signed by the token's key"
            )
    except VerificationError as exc:
        hint = ACCEPT_JWT_SCHEME if exc.code == "unsupported_scheme" else None
        raise Unauthorized.rejected(exc, hint) from None
    return Agent(
        id=claims.sub,
        provider=claims.iss.rstrip("/"),
        jkt=verified.thumbprint,
        jwk=claims.cnf.jwk,
        expires_at=claims.exp,
        person_server=claims.ps.rstrip("/") if claims.ps else None,
        token=verified.token,
    )


async def verify_server(
    request: httpsig.SignedRequest,
    discovery: Discovery,
    servers: set[str],
    dwk: str,
    now: int,
) -> str:
    """A server's signed request (`sig=jwks_uri` under `dwk`), from one of
    `servers`; only their keys are ever fetched. Its issuer, or a `401`."""
    named = httpsig.named_server(request.headers.get("signature-key", ""))
    if named not in servers:
        raise Unauthorized(
            "invalid_signature",
            "sign as a server this one takes requests from",
        )

    async def resolve(issuer: str, signed_dwk: str, kid: str) -> Jwk:
        # Only `dwk` is fetched, and only from an allowed server.
        if signed_dwk != dwk or issuer not in servers:
            raise VerificationError(
                "unsupported_scheme", f"sign with sig=jwks_uri and {dwk}"
            )
        return await discovery.key(issuer, signed_dwk, kid)

    try:
        verified = await httpsig.verify(request, now, resolve)
    except VerificationError as exc:
        raise Unauthorized.rejected(exc) from None
    if verified.scheme != "jwks_uri" or verified.dwk != dwk:
        raise Unauthorized(
            "unsupported_scheme", f"sign with sig=jwks_uri and {dwk}"
        )
    return str(verified.server)
