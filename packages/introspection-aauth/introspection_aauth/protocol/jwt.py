"""Compact JWS for AAuth's tokens, signed and verified under fully-specified
algorithms (`#token-format`)."""

import json
from dataclasses import dataclass
from typing import Any

from .errors import VerificationError
from .keys import SigningKey, b64url, b64url_decode
from .keys import verify as verify_signature

AGENT_TOKEN = "aa-agent+jwt"
PERSON_TOKEN = "aa-person+jwt"
RESOURCE_TOKEN = "aa-resource+jwt"
AUTH_TOKEN = "aa-auth+jwt"
#: How far a token's `iat` may be ahead of this clock.
CLOCK_SKEW_SECONDS = 60
#: The longest an agent or auth token may claim to live, so a forged one
#: cannot outlive the revocation of the key that signed it.
MAX_TOKEN_LIFETIME_SECONDS = 3_600


def encode(claims: dict[str, Any], key: SigningKey, typ: str) -> str:
    header = {"alg": "Ed25519", "typ": typ, "kid": key.kid}
    signing_input = ".".join(
        b64url(json.dumps(part, separators=(",", ":")).encode())
        for part in (header, claims)
    )
    return f"{signing_input}.{b64url(key.sign(signing_input.encode()))}"


@dataclass(frozen=True)
class Decoded:
    """A JWT split and decoded; nothing about it is verified yet."""

    header: dict[str, Any]
    claims: dict[str, Any]
    signing_input: bytes
    signature: bytes


def decode(token: str) -> Decoded:
    parts = token.split(".")
    if len(parts) != 3:
        raise VerificationError("invalid_jwt", "not a compact JWT")
    try:
        header, claims = (json.loads(b64url_decode(p)) for p in parts[:2])
        signature = b64url_decode(parts[2])
    except ValueError:
        raise VerificationError("invalid_jwt", "not a JWT") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise VerificationError("invalid_jwt", "not a JWT")
    return Decoded(
        header, claims, f"{parts[0]}.{parts[1]}".encode(), signature
    )


def verify(
    token: str,
    keys: dict[str, Any],
    typ: str,
    now: int,
    *,
    max_lifetime: int | None = None,
) -> dict[str, Any]:
    """The claims of `token`, signed by one of `keys` (a JWKS), of type `typ`,
    unexpired at `now`; `max_lifetime` caps `exp - iat`."""
    decoded = decode(token)
    if decoded.header.get("typ") != typ:
        raise VerificationError("invalid_jwt", f"not an {typ}")
    kid = decoded.header.get("kid")
    candidates = [
        k
        for k in keys.get("keys", [])
        if isinstance(k, dict) and (kid is None or k.get("kid") == kid)
    ]
    if not candidates:
        raise VerificationError("unknown_key", "signed by a key not published")
    if not any(
        k.get("alg") == decoded.header.get("alg")
        and verify_signature(k, decoded.signing_input, decoded.signature)
        for k in candidates
    ):
        raise VerificationError("invalid_jwt", "the signature does not verify")
    claims = decoded.claims
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, int) or not isinstance(iat, int):
        raise VerificationError("invalid_jwt", "exp and iat are required")
    if exp <= now:
        raise VerificationError("expired_jwt", "the token has expired")
    if iat > now + CLOCK_SKEW_SECONDS:
        raise VerificationError(
            "clock_skew", "the token's iat is in the future"
        )
    if max_lifetime is not None and exp - iat > max_lifetime:
        raise VerificationError(
            "invalid_jwt", "the token claims too long a life"
        )
    return claims
