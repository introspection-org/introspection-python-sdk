"""Keys: signing with Ed25519, verifying Ed25519 and ES256, RFC 7638 thumbprints.

Algorithms are the fully-specified ones (RFC 9864): a JWK's `alg` and a JWS
header say `Ed25519` or `ES256`, never `EdDSA`.
"""

import base64
import hashlib
import json
from collections.abc import Sequence
from typing import Any

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

from .errors import VerificationError

ALGORITHMS = {"Ed25519": ("OKP", "Ed25519"), "ES256": ("EC", "P-256")}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def s256(data: bytes) -> str:
    """The base64url SHA-256 of `data`, as AAuth hashes missions and proposals."""
    return b64url(hashlib.sha256(data).digest())


def thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638 thumbprint of an OKP or EC public key."""
    members = {"OKP": ("crv", "kty", "x"), "EC": ("crv", "kty", "x", "y")}
    names = members.get(jwk.get("kty", ""))
    if names is None or any(not isinstance(jwk.get(n), str) for n in names):
        raise VerificationError("invalid_key", "not an OKP or EC public key")
    canonical = json.dumps(
        {n: jwk[n] for n in names}, separators=(",", ":"), sort_keys=True
    )
    return s256(canonical.encode())


def algorithm(jwk: dict[str, Any]) -> str:
    """The key's algorithm, from its `alg`, which must match its type."""
    alg = jwk.get("alg")
    if alg not in ALGORITHMS:
        raise VerificationError(
            "unsupported_algorithm", "the key's alg is not Ed25519 or ES256"
        )
    if (jwk.get("kty"), jwk.get("crv")) != ALGORITHMS[alg]:
        raise VerificationError(
            "invalid_key", "the key's type is not its alg's"
        )
    return alg


def verify(jwk: dict[str, Any], data: bytes, signature: bytes) -> bool:
    """Whether `jwk` made `signature` over `data`."""
    try:
        if algorithm(jwk) == "Ed25519":
            Ed25519PublicKey.from_public_bytes(b64url_decode(jwk["x"])).verify(
                signature, data
            )
            return True
        if len(signature) != 64:
            return False
        public = ec.EllipticCurvePublicNumbers(
            int.from_bytes(b64url_decode(jwk["x"]), "big"),
            int.from_bytes(b64url_decode(jwk["y"]), "big"),
            ec.SECP256R1(),
        ).public_key()
        der = encode_dss_signature(
            int.from_bytes(signature[:32], "big"),
            int.from_bytes(signature[32:], "big"),
        )
        public.verify(der, data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


class SigningKey:
    """An Ed25519 signing key; its `kid` is its thumbprint."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._private = private_key
        raw = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        public = {"kty": "OKP", "crv": "Ed25519", "x": b64url(raw)}
        self.kid = thumbprint(public)
        self.public_jwk = {
            **public,
            "alg": "Ed25519",
            "kid": self.kid,
            "use": "sig",
        }

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


def jwks(keys: Sequence[SigningKey]) -> dict[str, Any]:
    """A JWKS publishing `keys`: the current key and any previous ones."""
    return {"keys": [k.public_jwk for k in keys]}
