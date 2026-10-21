"""Compact JWS for AAuth's tokens, signed and verified under fully-specified
algorithms (`#token-format`)."""

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from introspection_aauth.protocol.claims import (
    MAX_TOKEN_LIFETIME_SECONDS,
    Claims,
)
from introspection_aauth.protocol.errors import VerificationError
from introspection_aauth.protocol.json import JsonObject
from introspection_aauth.protocol.keys import (
    Jwk,
    Jwks,
    SigningKey,
    algorithm,
    b64url,
    b64url_decode,
)
from introspection_aauth.protocol.keys import verify as verify_signature

AGENT_TOKEN = "aa-agent+jwt"
PERSON_TOKEN = "aa-person+jwt"
RESOURCE_TOKEN = "aa-resource+jwt"
AUTH_TOKEN = "aa-auth+jwt"
#: How far a token's `iat` may be ahead of this clock.
CLOCK_SKEW_SECONDS = 60

__all__ = [
    "AGENT_TOKEN",
    "AUTH_TOKEN",
    "CLOCK_SKEW_SECONDS",
    "MAX_TOKEN_LIFETIME_SECONDS",
    "PERSON_TOKEN",
    "RESOURCE_TOKEN",
    "Decoded",
    "Header",
    "Unverified",
    "decode",
    "encode",
    "peek",
    "verify",
]

ClaimsModel = TypeVar("ClaimsModel", bound=Claims)
JSON_OBJECT = TypeAdapter(JsonObject)


class Header(BaseModel):
    """A JWS header, as AAuth's tokens use it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    alg: str | None = None
    typ: str | None = None
    kid: str | None = None


class Unverified(BaseModel):
    """What may be read of a token before it is verified, to decide whose keys
    to fetch: nothing here is to be trusted."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    iss: str | None = None
    dwk: str | None = None
    tenant: str | None = None
    mission_s256: str | None = None


def _algorithm(key: Jwk) -> str | None:
    """A key's algorithm, or None for one this library does not verify with."""
    try:
        return algorithm(key)
    except VerificationError:
        return None


def encode(claims: Claims, key: SigningKey, typ: str) -> str:
    header = Header(alg="Ed25519", typ=typ, kid=key.kid)
    signing_input = ".".join(
        b64url(part.model_dump_json(exclude_none=True).encode())
        for part in (header, claims)
    )
    return f"{signing_input}.{b64url(key.sign(signing_input.encode()))}"


@dataclass(frozen=True)
class Decoded:
    """A JWT split and decoded; nothing about it is verified yet."""

    header: Header
    claims: JsonObject
    signing_input: bytes
    signature: bytes


def decode(token: str) -> Decoded:
    parts = token.split(".")
    if len(parts) != 3:
        raise VerificationError("invalid_jwt", "not a compact JWT")
    try:
        header = Header.model_validate_json(b64url_decode(parts[0]))
        claims = JSON_OBJECT.validate_json(b64url_decode(parts[1]))
        signature = b64url_decode(parts[2])
    except (ValueError, ValidationError):
        raise VerificationError("invalid_jwt", "not a JWT") from None
    return Decoded(
        header, claims, f"{parts[0]}.{parts[1]}".encode(), signature
    )


def peek(token: str) -> tuple[Header, Unverified]:
    """A token's header and what it says of itself, unverified."""
    decoded = decode(token)
    try:
        return decoded.header, Unverified.model_validate(decoded.claims)
    except ValidationError:
        raise VerificationError("invalid_jwt", "not a JWT") from None


def verify(
    token: str,
    keys: Jwks,
    typ: str,
    now: int,
    model: type[ClaimsModel],
) -> ClaimsModel:
    """The claims of `token`, read into `model`: signed by one of `keys`, of
    type `typ`, unexpired at `now`, and valid as that token on its own."""
    decoded = decode(token)
    if decoded.header.typ != typ:
        raise VerificationError("invalid_jwt", f"not an {typ}")
    kid = decoded.header.kid
    candidates = [k for k in keys.keys if kid is None or k.kid == kid]
    if not candidates:
        raise VerificationError("unknown_key", "signed by a key not published")
    if not any(
        _algorithm(k) == decoded.header.alg
        and verify_signature(k, decoded.signing_input, decoded.signature)
        for k in candidates
    ):
        raise VerificationError("invalid_jwt", "the signature does not verify")
    try:
        claims = model.model_validate(decoded.claims)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        raise VerificationError(
            "invalid_jwt",
            f"{where}: {error['msg']}" if where else error["msg"],
        ) from None
    if claims.exp <= now:
        raise VerificationError("expired_jwt", "the token has expired")
    if claims.iat > now + CLOCK_SKEW_SECONDS:
        raise VerificationError(
            "clock_skew", "the token's iat is in the future"
        )
    return claims
