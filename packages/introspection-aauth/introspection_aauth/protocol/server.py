"""What a Person Server and an Access Server both do as servers: sign as
themselves, verify the agents and servers that call them, read a resource's
R3 proposal, and answer a request that has to wait."""

import logging
import time
import uuid
from collections.abc import Sequence
from typing import NotRequired, Protocol, TypedDict, TypeVar, Unpack
from urllib.parse import urlsplit

import http_sfv
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
    ResourceTokenExpectation,
)
from .discovery import Discovery
from .errors import AAuthError, Answer, VerificationError
from .keys import Jwk, Jwks, SigningKey, jwks, s256
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
    "presented_token_error",
    "requirement",
    "same_origin",
    "verify_agent",
    "verify_agent_token",
    "verify_resource_token",
    "verify_server",
]

logger = logging.getLogger(__name__)

Model = TypeVar("Model", bound=BaseModel)
ClaimsModel = TypeVar("ClaimsModel", bound=Claims)


def now_seconds() -> int:
    return int(time.time())


#: How a `401` names the scheme an agent should sign with.
ACCEPT_JWT_SCHEME = {"Accept-Signature-Scheme": "jwt"}


def https_origin(value: str) -> bool:
    """A server identifier: `https://host`, with no path, query or fragment."""
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


def _origin(url: str) -> str | None:
    """The https origin `url` is on, or None for any other URL or one
    carrying credentials."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        return None
    return f"https://{parts.netloc.lower()}"


def same_origin(url: str, origin: str) -> bool:
    """Whether `url` is an https URL on `origin`, with no credentials in it."""
    found = _origin(url)
    return found is not None and found == _origin(origin)


def requirement(
    name: str, *, url: str | None = None, code: str | None = None
) -> str:
    """An `AAuth-Requirement` header (`#requirement-values`): an RFC 9651
    Dictionary whose `requirement` carries its parameters, strings escaped."""
    item = http_sfv.Item(http_sfv.Token(name))
    if url is not None:
        item.params["url"] = url
    if code is not None:
        item.params["code"] = code
    header = http_sfv.Dictionary()
    header["requirement"] = item
    return str(header)


def presented_token_error(exc: VerificationError) -> AAuthError:
    """The refusal of a presented person token that does not verify."""
    code = (
        "expired_presented_token"
        if exc.code == "expired_jwt"
        else "invalid_presented_token"
    )
    return AAuthError(400, code, exc.detail)


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
            "AAuth-Requirement": requirement or APPROVAL_REQUIREMENT,
        },
    )


APPROVAL_REQUIREMENT = "requirement=approval"


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
        self,
        http: httpx.AsyncClient,
        resource: str,
        r3_uri: str,
        r3_s256: str,
        now: int,
    ) -> R3Proposal:
        """A resource's R3 proposal, fetched signed and checked against its
        hash; only from the resource's own https origin, so a resource token
        cannot send this server anywhere else."""
        if not same_origin(r3_uri, resource):
            raise ValueError("the proposal is not on the resource's origin")
        response = await http.get(
            r3_uri,
            headers=self.signed("GET", r3_uri, None, now),
            follow_redirects=False,
        )
        response.raise_for_status()
        if s256(response.content) != r3_s256:
            raise ValueError("the proposal does not match its hash")
        return R3Proposal.model_validate_json(response.content)

    async def summary(
        self,
        http: httpx.AsyncClient,
        resource: str,
        r3_uri: str,
        r3_s256: str,
        now: int,
    ) -> str | None:
        """A proposal's one-line summary, or None when there is none or it
        cannot be read: a request stands without one."""
        try:
            proposal = await self.read_proposal(
                http, resource, r3_uri, r3_s256, now
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "r3 proposal not read",
                extra={"resource": resource, "error": type(exc).__name__},
            )
            return None
        summary = proposal.display.summary if proposal.display else None
        return summary[:MAX_SUMMARY_CHARS] if summary else None


#: The longest summary of a proposal shown to whoever decides.
MAX_SUMMARY_CHARS = 2_000


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
    #: How it reads metadata and keys; by default, over its `http`.
    discovery: NotRequired[Discovery]


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
        self.discovery = options.get("discovery") or Discovery(http)
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
        raise AAuthError(
            400, "invalid_resource_token", f"does not verify: {exc.detail}"
        ) from None
    wrong = expectation.failures(rt)
    if wrong:
        raise AAuthError(
            400,
            "invalid_resource_token",
            f"its {', '.join(wrong)} not this request's",
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
        raise AAuthError(401, exc.code, exc.detail, hint) from None
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
        raise AAuthError(401, exc.code, exc.detail) from None
    if verified.scheme != "jwks_uri" or verified.dwk != dwk:
        raise AAuthError(
            401, "unsupported_scheme", f"sign with sig=jwks_uri and {dwk}"
        )
    return str(verified.server)
