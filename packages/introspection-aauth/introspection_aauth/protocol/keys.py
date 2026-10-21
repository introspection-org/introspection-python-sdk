"""Keys: signing with Ed25519, verifying Ed25519 and ES256, RFC 7638 thumbprints.

Algorithms are the fully-specified ones (RFC 9864): a JWK's `alg` and a JWS
header say `Ed25519` or `ES256`, never `EdDSA`.
"""

import base64
import hashlib
import json
from collections.abc import Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.utils import (
    encode_dss_signature,
)
from pydantic import BaseModel, ConfigDict

from .errors import VerificationError

ALGORITHMS = {"Ed25519": ("OKP", "Ed25519"), "ES256": ("EC", "P-256")}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class Jwk(BaseModel):
    """A public JSON Web Key (RFC 7517), as AAuth's keys are: OKP or EC."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kty: str
    crv: str | None = None
    x: str | None = None
    y: str | None = None
    alg: str | None = None
    kid: str | None = None
    use: str | None = None


class Jwks(BaseModel):
    """A JSON Web Key Set."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    keys: list[Jwk]


def s256(data: bytes) -> str:
    """The base64url SHA-256 of `data`, as AAuth hashes missions and proposals."""
    return b64url(hashlib.sha256(data).digest())


def thumbprint(jwk: Jwk) -> str:
    """RFC 7638 thumbprint of an OKP or EC public key: SHA-256 over its
    required members only, as JSON with sorted keys and no whitespace."""
    if jwk.kty == "OKP" and jwk.crv and jwk.x:
        members = {"crv": jwk.crv, "kty": jwk.kty, "x": jwk.x}
    elif jwk.kty == "EC" and jwk.crv and jwk.x and jwk.y:
        members = {"crv": jwk.crv, "kty": jwk.kty, "x": jwk.x, "y": jwk.y}
    else:
        raise VerificationError("invalid_key", "not an OKP or EC public key")
    canonical = json.dumps(members, separators=(",", ":"), sort_keys=True)
    return s256(canonical.encode())


def algorithm(jwk: Jwk) -> str:
    """The key's algorithm: its `alg`, which must match its type, or, with
    no `alg` (RFC 7800 does not require one), the one its type names."""
    named = jwk.alg or next(
        (
            alg
            for alg, kind in ALGORITHMS.items()
            if kind == (jwk.kty, jwk.crv)
        ),
        None,
    )
    if named is None or named not in ALGORITHMS:
        raise VerificationError(
            "unsupported_algorithm", "the key is not Ed25519 or ES256"
        )
    if (jwk.kty, jwk.crv) != ALGORITHMS[named]:
        raise VerificationError(
            "invalid_key", "the key's type is not its alg's"
        )
    return named


def verify(jwk: Jwk, data: bytes, signature: bytes) -> bool:
    """Whether `jwk` made `signature` over `data`."""
    try:
        alg = algorithm(jwk)
        if jwk.x is None:
            return False
        if alg == "Ed25519":
            Ed25519PublicKey.from_public_bytes(b64url_decode(jwk.x)).verify(
                signature, data
            )
            return True
        if len(signature) != 64 or jwk.y is None:
            return False
        public = ec.EllipticCurvePublicNumbers(
            int.from_bytes(b64url_decode(jwk.x), "big"),
            int.from_bytes(b64url_decode(jwk.y), "big"),
            ec.SECP256R1(),
        ).public_key()
        der = encode_dss_signature(
            int.from_bytes(signature[:32], "big"),
            int.from_bytes(signature[32:], "big"),
        )
        public.verify(der, data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, VerificationError):
        return False


class SigningKey:
    """An Ed25519 signing key; its `kid` is its thumbprint."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._private = private_key
        raw = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.kid = thumbprint(Jwk(kty="OKP", crv="Ed25519", x=b64url(raw)))
        self.public_jwk = Jwk(
            kty="OKP",
            crv="Ed25519",
            x=b64url(raw),
            alg="Ed25519",
            kid=self.kid,
            use="sig",
        )

    @classmethod
    def generate(cls) -> "SigningKey":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_pem(cls, pem: str | bytes) -> "SigningKey":
        key = serialization.load_pem_private_key(
            pem.encode() if isinstance(pem, str) else pem, password=None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("an AAuth signing key is an Ed25519 PKCS#8 PEM")
        return cls(key)

    @classmethod
    def from_seed(cls, seed: bytes) -> "SigningKey":
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    def sign(self, data: bytes) -> bytes:
        return self._private.sign(data)


def jwks(keys: Sequence[SigningKey]) -> Jwks:
    """A JWKS publishing `keys`: the current key and any previous ones."""
    return Jwks(keys=[k.public_jwk for k in keys])
