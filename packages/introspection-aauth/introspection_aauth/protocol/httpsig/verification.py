"""Verifying an RFC 9421 signed request with `Signature-Key`: which key signed
it, whether every required component is covered, and whether the signature
holds."""

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import http_sfv
from http_sfv.item import Parameters
from pydantic import ValidationError

from introspection_aauth.protocol import jwt
from introspection_aauth.protocol.claims import Confirmation
from introspection_aauth.protocol.errors import VerificationError
from introspection_aauth.protocol.httpsig.signing import (
    KNOWN_DWKS,
    MAX_CLOCK_SKEW_SECONDS,
    REQUIRED,
    authority,
    content_digest,
)
from introspection_aauth.protocol.keys import Jwk, thumbprint
from introspection_aauth.protocol.keys import verify as verify_with


class KeyResolver(Protocol):
    """Finds a published key: a server's `id`, its `dwk` and the key's `kid`."""

    def __call__(
        self, server: str, dwk: str, kid: str, /
    ) -> Awaitable[Jwk]: ...


@dataclass(frozen=True)
class KeyNaming:
    """How a key was named: the token presented, or the server and document."""

    token: str | None = None
    server: str | None = None
    dwk: str | None = None


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
) -> tuple[Jwk, KeyNaming]:
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
        return jwk, KeyNaming(token=token)
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
        return await resolve(server, dwk, kid), KeyNaming(
            server=server, dwk=dwk
        )
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
