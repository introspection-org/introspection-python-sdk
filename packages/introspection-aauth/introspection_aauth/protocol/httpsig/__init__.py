"""RFC 9421 HTTP Message Signatures under the AAuth profile, with the
signer's key named in `Signature-Key` (draft-hardt-httpbis-signature-key).

`sign` covers `@method`, `@authority`, `@path`, `@query` when there is one,
`signature-key`, and for a request with a body `content-digest` and
`content-type`. `verify` checks a signature and returns the key that made
it; a token in the `jwt` scheme is decoded but not verified, which is the
caller's job against its issuer's keys.
"""

from introspection_aauth.protocol.httpsig.signing import (
    KNOWN_DWKS,
    LABEL,
    MAX_CLOCK_SKEW_SECONDS,
    REQUIRED,
    authority,
    content_digest,
    jwks_uri_key,
    jwt_key,
    named_server,
    sign,
    signature_scheme,
)
from introspection_aauth.protocol.httpsig.verification import (
    KeyResolver,
    SignedRequest,
    Verified,
    verify,
)

__all__ = [
    "KNOWN_DWKS",
    "LABEL",
    "MAX_CLOCK_SKEW_SECONDS",
    "REQUIRED",
    "KeyResolver",
    "SignedRequest",
    "Verified",
    "authority",
    "content_digest",
    "jwks_uri_key",
    "jwt_key",
    "named_server",
    "sign",
    "signature_scheme",
    "verify",
]
