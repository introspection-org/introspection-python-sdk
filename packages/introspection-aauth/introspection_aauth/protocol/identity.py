"""A server's own identity: its issuer, signing keys and published keys, the
tokens and requests it signs, and the R3 proposals it reads."""

import logging
from collections.abc import Sequence

import httpx2 as httpx

from introspection_aauth.protocol import httpsig, jwt
from introspection_aauth.protocol.claims import (
    Claims,
    ServerDwk,
)
from introspection_aauth.protocol.errors import (
    VerificationError,
)
from introspection_aauth.protocol.keys import Jwks, SigningKey, jwks, s256
from introspection_aauth.protocol.urls import (
    https_origin,
    same_origin,
)
from introspection_aauth.protocol.verification import (
    ClaimsModel,
)
from introspection_aauth.protocol.wire import R3Proposal

logger = logging.getLogger(__name__)


class Identity:
    """A server's identifier and keys: the current key signs, and the
    previous ones stay published until what they signed has expired."""

    def __init__(
        self,
        issuer: str,
        dwk: ServerDwk,
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
