"""RFC 9421 HTTP Message Signatures under the AAuth profile, with the
signer's key named in `Signature-Key` (draft-hardt-httpbis-signature-key).

`sign` covers `@method`, `@authority`, `@path`, `@query` when there is one,
`signature-key`, and for a request with a body `content-digest` and
`content-type`. `verify` checks a signature and returns the key that made
it; a token in the `jwt` scheme is decoded but not verified, which is the
caller's job against its issuer's keys.
"""

import base64
import hashlib
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import http_sfv
from http_sfv.item import Parameters
from pydantic import ValidationError

from . import jwt
from .claims import Confirmation
from .errors import VerificationError
from .keys import Jwk, SigningKey, thumbprint
from .keys import verify as verify_with

LABEL = "sig"
REQUIRED = ("@method", "@authority", "@path", "signature-key")
MAX_CLOCK_SKEW_SECONDS = 60
#: Metadata documents a `jwks_uri` key may be named under (`#metadata-documents`).
KNOWN_DWKS = frozenset(
    {
        "aauth-agent.json",
        "aauth-person.json",
        "aauth-access.json",
        "aauth-resource.json",
    }
)


class KeyResolver(Protocol):
    """Finds a published key: a server's `id`, its `dwk` and the key's `kid`."""

    def __call__(
        self, server: str, dwk: str, kid: str, /
    ) -> Awaitable[Jwk]: ...


@dataclass(frozen=True)
class _Named:
    """How a key was named: the token presented, or the server and document."""

    token: str | None = None
    server: str | None = None
    dwk: str | None = None


def _quoted(value: str) -> str:
    if '"' in value or "\\" in value or not value.isascii():
        raise ValueError("value cannot travel in Signature-Key")
    return f'"{value}"'


def jwt_key(token: str) -> str:
    """`Signature-Key` presenting a token whose `cnf.jwk` is the key."""
    return f"{LABEL}=jwt;jwt={_quoted(token)}"


def jwks_uri_key(server: str, dwk: str, kid: str) -> str:
    """`Signature-Key` naming a server's published key."""
    return (
        f"{LABEL}=jwks_uri;id={_quoted(server)};dwk={_quoted(dwk)};"
        f"kid={_quoted(kid)}"
    )


def _signature_key(signature_key: str) -> http_sfv.Item | None:
    parsed = http_sfv.Dictionary()
    try:
        parsed.parse(signature_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
    if len(parsed) != 1:
        return None
    item = next(iter(parsed.values()))
    return item if isinstance(item, http_sfv.Item) else None


def signature_scheme(signature_key: str) -> str | None:
    """The scheme a Signature-Key names, read before anything is fetched."""
    item = _signature_key(signature_key)
    return str(item.value) if item is not None else None


def named_server(signature_key: str) -> str | None:
    """The server a `jwks_uri` Signature-Key names, read before any key is
    fetched, so a verifier can refuse a server it does not take requests from."""
    item = _signature_key(signature_key)
    if item is None or str(item.value) != "jwks_uri":
        return None
    server = item.params.get("id")
    return server if isinstance(server, str) else None


def content_digest(body: bytes) -> str:
    """`sha-256=:…:`, the RFC 9530 `Content-Digest` of `body`."""
    return (
        f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"
    )


def authority(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"{url} has no host")
    return f"{host}:{parts.port}" if parts.port else host


def sign(
    key: SigningKey,
    signature_key: str,
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
    authorization: str | None = None,
    created: int,
) -> dict[str, str]:
    """The headers that sign a request to `url` with `key`, covering its
    `Authorization` when it carries one."""
    parts = urlsplit(url)
    covered = [
        ("@method", method.upper()),
        ("@authority", authority(url)),
        ("@path", parts.path or "/"),
    ]
    if parts.query:
        covered.append(("@query", f"?{parts.query}"))
    covered.append(("signature-key", signature_key))
    headers: dict[str, str] = {}
    if body:
        digest = content_digest(body)
        covered += [("content-digest", digest), ("content-type", content_type)]
        headers |= {"content-digest": digest, "content-type": content_type}
    if authorization is not None:
        covered.append(("authorization", authorization))
        headers["authorization"] = authorization
    params = (
        "("
        + " ".join(f'"{name}"' for name, _ in covered)
        + f");created={created}"
    )
    base = "\n".join(
        [f'"{name}": {value}' for name, value in covered]
        + [f'"@signature-params": {params}']
    )
    signature = base64.b64encode(key.sign(base.encode())).decode()
    return headers | {
        "signature-key": signature_key,
        "signature-input": f"{LABEL}={params}",
        "signature": f"{LABEL}=:{signature}:",
    }


@dataclass(frozen=True)
class SignedRequest:
    """A request as its signer addressed it: `url` is the one it signed,
    whatever proxy or rewrite delivered it."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None

    def __post_init__(self) -> None:
        lowered = {k.lower(): v for k, v in self.headers.items()}
        object.__setattr__(self, "headers", lowered)


@dataclass(frozen=True)
class Verified:
    """A signature that verified, and how its key was named."""

    scheme: str
    jwk: Jwk
    thumbprint: str
    created: int
    #: The presented token, for the `jwt` scheme: decoded, not verified.
    token: str | None = None
    #: The server and document, for the `jwks_uri` scheme.
    server: str | None = None
    dwk: str | None = None


def _dictionary(headers: Mapping[str, str], name: str) -> http_sfv.Dictionary:
    value = headers.get(name)
    if not value:
        raise VerificationError("invalid_signature", f"missing {name}")
    parsed = http_sfv.Dictionary()
    try:
        parsed.parse(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise VerificationError(
            "invalid_signature", f"{name} is malformed"
        ) from None
    return parsed


def _covered(signature_input: http_sfv.InnerList) -> list[str]:
    names: list[str] = []
    for item in signature_input:
        if (
            not isinstance(item.value, str)
            or item.params
            or item.value in names
        ):
            raise VerificationError(
                "invalid_input", "only plain, distinct components"
            )
        names.append(item.value)
    missing = [c for c in REQUIRED if c not in names]
    if missing:
        raise VerificationError(
            "invalid_input", f"{missing[0]} must be covered"
        )
    return names


async def _key(
    scheme: str, params: Parameters, resolve: KeyResolver | None
) -> tuple[Jwk, _Named]:
    if scheme == "jwt":
        token = params.get("jwt")
        if not isinstance(token, str):
            raise VerificationError(
                "invalid_key", "the jwt scheme carries a jwt"
            )
        cnf = jwt.decode(token).claims.get("cnf")
        try:
            jwk = Confirmation.model_validate(cnf).jwk
        except ValidationError:
            raise VerificationError(
                "invalid_jwt", "the token has no cnf.jwk"
            ) from None
        return jwk, _Named(token=token)
    if scheme == "jwks_uri":
        server, dwk, kid = (params.get(n) for n in ("id", "dwk", "kid"))
        if not (
            isinstance(server, str)
            and isinstance(dwk, str)
            and isinstance(kid, str)
        ):
            raise VerificationError(
                "invalid_key", "jwks_uri needs id, dwk and kid"
            )
        if dwk not in KNOWN_DWKS or resolve is None:
            raise VerificationError(
                "invalid_key", "not a server this verifier reads"
            )
        return await resolve(server, dwk, kid), _Named(server=server, dwk=dwk)
    raise VerificationError("unsupported_scheme", f"the {scheme} scheme")


def _component(name: str, request: SignedRequest) -> str:
    parts = urlsplit(request.url)
    derived = {
        "@method": request.method.upper(),
        "@authority": authority(request.url),
        "@path": parts.path or "/",
        "@query": f"?{parts.query}",
    }
    if name in derived:
        return derived[name]
    if name.startswith("@") or name not in request.headers:
        raise VerificationError("invalid_input", f"{name} cannot be covered")
    return request.headers[name].strip()


async def verify(
    request: SignedRequest,
    now: int,
    resolve: KeyResolver | None = None,
) -> Verified:
    """Verify `request`'s signature; `resolve` finds a `jwks_uri` key."""
    headers, body = request.headers, request.body
    keys = _dictionary(headers, "signature-key")
    if len(keys) != 1:
        raise VerificationError("invalid_key", "Signature-Key has one member")
    label, item = next(iter(keys.items()))
    if not isinstance(item, http_sfv.Item) or not isinstance(
        item.value, http_sfv.Token
    ):
        raise VerificationError("invalid_key", "Signature-Key names a scheme")
    inputs = _dictionary(headers, "signature-input")
    signature_input = inputs.get(label)
    if not isinstance(signature_input, http_sfv.InnerList):
        raise VerificationError(
            "invalid_signature", "no Signature-Input for the key"
        )
    names = _covered(signature_input)
    created = signature_input.params.get("created")
    if not isinstance(created, int):
        raise VerificationError(
            "invalid_signature", "Signature-Input has no created"
        )
    if created > now + MAX_CLOCK_SKEW_SECONDS:
        raise VerificationError("clock_skew", "created is ahead of this clock")
    if now - created > MAX_CLOCK_SKEW_SECONDS:
        raise VerificationError("invalid_signature", "the signature is stale")
    jwk, named = await _key(str(item.value), item.params, resolve)
    if body:
        for required in ("content-digest", "content-type"):
            if required not in names:
                raise VerificationError(
                    "invalid_input", f"{required} must be covered"
                )
    # Required when present, per the AAuth-Access rule; this library does
    # not issue AAuth-Access yet.
    if "authorization" in headers and "authorization" not in names:
        raise VerificationError(
            "invalid_input", "authorization must be covered"
        )
    if "content-digest" in names and headers.get(
        "content-digest"
    ) != content_digest(body or b""):
        raise VerificationError(
            "invalid_input", "content-digest is not the body's"
        )
    base = "\n".join(
        [f'"{n}": {_component(n, request)}' for n in names]
        + [f'"@signature-params": {signature_input}']
    )
    signature = _dictionary(headers, "signature").get(label)
    if not isinstance(signature, http_sfv.Item) or not isinstance(
        signature.value, bytes
    ):
        raise VerificationError(
            "invalid_signature", "no Signature for the key"
        )
    if not verify_with(jwk, base.encode(), signature.value):
        raise VerificationError(
            "invalid_signature", "the signature does not verify"
        )
    return Verified(
        str(item.value),
        jwk,
        thumbprint(jwk),
        created,
        token=named.token,
        server=named.server,
        dwk=named.dwk,
    )
