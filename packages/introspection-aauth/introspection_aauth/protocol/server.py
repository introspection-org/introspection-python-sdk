"""What a Person Server and an Access Server both do as servers: sign as
themselves, verify the agents and servers that call them, read a resource's
R3 proposal, and answer a request that has to wait."""

import time
import uuid
from collections.abc import Sequence
from typing import NotRequired, Protocol, TypedDict, TypeVar, Unpack
from urllib.parse import urlsplit

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from . import httpsig, jwt
from .claims import (
    ACCESS_DWK,
    AGENT_DWK,
    PERSON_DWK,
    RESOURCE_DWK,
    AgentTokenClaims,
    Claims,
    ResourceTokenClaims,
)
from .discovery import Discovery
from .errors import AAuthError, Answer, VerificationError
from .keys import Jwks, SigningKey, jwks, s256
from .models import Agent
from .wire import Pending, R3Proposal

__all__ = [
    "ACCESS_DWK",
    "AGENT_DWK",
    "PERSON_DWK",
    "RESOURCE_DWK",
    "Clock",
    "IdFactory",
    "Identity",
    "Server",
    "ServerOptions",
    "https_origin",
    "now_seconds",
    "parse",
    "pending",
    "verify_agent",
    "verify_agent_token",
    "verify_server",
]

Model = TypeVar("Model", bound=BaseModel)
ClaimsModel = TypeVar("ClaimsModel", bound=Claims)


def now_seconds() -> int:
    return int(time.time())


def https_origin(value: object) -> bool:
    """A server identifier: `https://host`, with no path, query or fragment."""
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and not parts.path.strip("/")
        and not parts.query
        and not parts.fragment
    )


def parse(model: type[Model], body: bytes | None) -> Model:
    """A request body, or `400 invalid_request`."""
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError as exc:
        raise AAuthError(
            400, "invalid_request", exc.errors()[0]["msg"]
        ) from None


def pending(
    location: str, retry_after: int, requirement: str | None = None
) -> Answer:
    """`202`: poll `location` (`#deferred-responses`)."""
    return Answer(
        202,
        Pending(),
        {
            "Location": location,
            "Retry-After": str(retry_after),
            "Cache-Control": "no-store",
            "AAuth-Requirement": requirement or "requirement=approval",
        },
    )


class Identity:
    """A server's identifier and keys: the current key signs, and the
    previous ones stay published until what they signed has expired."""

    def __init__(
        self,
        issuer: str,
        dwk: str,
        signing_key: SigningKey,
        previous_keys: Sequence[SigningKey] = (),
    ):
        if not https_origin(issuer):
            raise ValueError("an issuer is an https origin with no path")
        self.issuer = issuer.rstrip("/")
        self.dwk = dwk
        self.key = signing_key
        self.keys = [signing_key, *previous_keys]

    def jwks(self) -> Jwks:
        return jwks(self.keys)

    def token(self, claims: Claims, typ: str) -> str:
        return jwt.encode(claims, self.key, typ)

    def verify_own(
        self, token: str, typ: str, now: int, model: type[ClaimsModel]
    ) -> ClaimsModel:
        claims = jwt.verify(token, self.jwks(), typ, now, model)
        if claims.iss != self.issuer:
            raise VerificationError("invalid_jwt", "not issued here")
        return claims

    def signed(
        self, method: str, url: str, body: bytes | None, now: int
    ) -> dict[str, str]:
        """Headers signing a request as this server (`sig=jwks_uri`)."""
        key = httpsig.jwks_uri_key(self.issuer, self.dwk, self.key.kid)
        return httpsig.sign(self.key, key, method, url, body=body, created=now)

    async def read_proposal(
        self, http: httpx.AsyncClient, r3_uri: str, r3_s256: str, now: int
    ) -> R3Proposal:
        """A resource's R3 proposal, fetched signed and checked against its hash."""
        response = await http.get(
            r3_uri, headers=self.signed("GET", r3_uri, None, now)
        )
        response.raise_for_status()
        if s256(response.content) != r3_s256:
            raise ValueError("the proposal does not match its hash")
        return R3Proposal.model_validate_json(response.content)


def new_hex_id() -> str:
    return uuid.uuid4().hex


class Clock(Protocol):
    """Now, in whole seconds since the epoch."""

    def __call__(self) -> int: ...


class IdFactory(Protocol):
    """A new id, unique to this server."""

    def __call__(self) -> str: ...


class ServerOptions(TypedDict):
    """What every server takes besides its own: its keys' predecessors, where
    its protocol routes live, its clock and ids, and how long to wait."""

    previous_keys: NotRequired[Sequence[SigningKey]]
    #: The URL its protocol routes are under, e.g. `{issuer}/aauth`.
    endpoint_base: NotRequired[str]
    retry_after: NotRequired[int]
    clock: NotRequired[Clock]
    new_id: NotRequired[IdFactory]
    name: NotRequired[str]


class Server:
    """A server's identity, its HTTP client and discovery, and its options."""

    def __init__(
        self,
        issuer: str,
        dwk: str,
        signing_key: SigningKey,
        http: httpx.AsyncClient,
        **options: Unpack[ServerOptions],
    ):
        self.identity = Identity(
            issuer, dwk, signing_key, options.get("previous_keys", ())
        )
        self.issuer = self.identity.issuer
        self.http = http
        self.discovery = Discovery(http)
        self.endpoint_base = options.get("endpoint_base", self.issuer).rstrip(
            "/"
        )
        self.retry_after = options.get("retry_after", 5)
        self.clock: Clock = options.get("clock", now_seconds)
        self.new_id: IdFactory = options.get("new_id", new_hex_id)
        self.name = options.get("name")

    def jwks(self) -> Jwks:
        return self.identity.jwks()

    def metadata(self) -> BaseModel:
        """Its `/.well-known` metadata document."""
        raise NotImplementedError


async def verify_resource_token(
    token: str, discovery: Discovery, resource: str, now: int
) -> ResourceTokenClaims:
    """A resource token, against its resource's keys (`#resource-token`)."""
    return await discovery.verified(
        resource,
        RESOURCE_DWK,
        lambda keys: jwt.verify(
            token, keys, jwt.RESOURCE_TOKEN, now, ResourceTokenClaims
        ),
    )


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
    """An agent's signed request (`sig=jwt`, its agent token), or a `401`."""
    try:
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
        headers = (
            {"Accept-Signature-Scheme": "jwt"}
            if exc.code == "unsupported_scheme"
            else {}
        )
        raise AAuthError(401, exc.code, exc.detail, headers) from None
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
        raise AAuthError(
            401,
            "invalid_signature",
            "sign as a server this one takes requests from",
        )
    try:
        verified = await httpsig.verify(request, now, discovery.key)
    except VerificationError as exc:
        raise AAuthError(401, exc.code, exc.detail) from None
    if verified.scheme != "jwks_uri" or verified.dwk != dwk:
        raise AAuthError(
            401, "unsupported_scheme", f"sign with sig=jwks_uri and {dwk}"
        )
    return str(verified.server)
