"""Metadata and keys: `{issuer}/.well-known/{dwk}` → `jwks_uri` → JWKS
(`#metadata-documents`), cached for a bounded time."""

import time
from collections.abc import Callable
from typing import Protocol, TypeVar
from urllib.parse import urlsplit

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from .errors import VerificationError
from .keys import Jwk, Jwks
from .wire import ServerMetadata

T = TypeVar("T")
Document = TypeVar("Document", bound=BaseModel)
#: How long an issuer's keys are trusted before they are fetched again.
KEYS_TTL_SECONDS = 300
#: The least time between refetches forced by a token that failed to verify.
REFRESH_MIN_SECONDS = 30


def is_identifier(value: str) -> bool:
    """Whether `value` is an AAuth server identifier (`#server-identifiers`):
    `https://` and a lowercase host, with no port, path, userinfo, query,
    fragment or trailing slash."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname or ""
    return (
        parts.scheme == "https"
        and bool(host)
        and parts.netloc == host == host.lower()
        and port is None
        and not (parts.path or parts.query or parts.fragment)
        and "#" not in value
        and "?" not in value
    )


def is_https(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname)


class Monotonic(Protocol):
    """Seconds on a clock that never goes back, for timing the cache."""

    def __call__(self) -> float: ...


class Discovery:
    """Fetches issuers' metadata and keys over `http`."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        ttl_seconds: int = KEYS_TTL_SECONDS,
        refresh_min_seconds: int = REFRESH_MIN_SECONDS,
        clock: Monotonic = time.monotonic,
    ):
        self.http = http
        self._ttl = ttl_seconds
        self._refresh_min = refresh_min_seconds
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, Jwks]] = {}

    async def metadata(self, issuer: str, dwk: str) -> ServerMetadata:
        """The issuer's metadata document, which must name it as `issuer`
        and publish its keys over https."""
        if not is_identifier(issuer):
            raise VerificationError(
                "invalid_issuer", f"{issuer} is not an AAuth server identifier"
            )
        document = await self.get(
            f"{issuer}/.well-known/{dwk}", ServerMetadata
        )
        if document.issuer != issuer:
            raise VerificationError(
                "issuer_mismatch", "metadata names another issuer"
            )
        if document.jwks_uri is not None and not is_https(document.jwks_uri):
            raise VerificationError(
                "invalid_metadata", "its jwks_uri is not https"
            )
        return document

    async def jwks(
        self, issuer: str, dwk: str, *, refresh: bool = False
    ) -> Jwks:
        """The issuer's keys; `refresh` fetches again keys that failed, since an
        issuer may rotate a key, but no more often than `refresh_min_seconds`."""
        cached = self._cache.get((issuer, dwk))
        now = self._clock()
        if cached and cached[0] > now:
            fetched_at = cached[0] - self._ttl
            if not refresh or now - fetched_at < self._refresh_min:
                return cached[1]
        document = await self.metadata(issuer, dwk)
        if document.jwks is not None:
            keys = document.jwks
        elif document.jwks_uri is not None:
            keys = await self.get(document.jwks_uri, Jwks)
        else:
            raise VerificationError(
                "unknown_key", f"{issuer} publishes no keys"
            )
        self._cache[(issuer, dwk)] = (self._clock() + self._ttl, keys)
        return keys

    async def verified(
        self, issuer: str, dwk: str, check: Callable[[Jwks], T]
    ) -> T:
        """`check` against the issuer's keys, and once more against fresh ones."""
        try:
            return check(await self.jwks(issuer, dwk))
        except VerificationError:
            return check(await self.jwks(issuer, dwk, refresh=True))

    async def key(self, issuer: str, dwk: str, kid: str) -> Jwk:
        """One published key, by `kid`: how a `jwks_uri` signature is resolved."""
        for refresh in (False, True):
            keys = await self.jwks(issuer, dwk, refresh=refresh)
            for key in keys.keys:
                if key.kid == kid:
                    return key
        raise VerificationError("unknown_key", f"no key {kid} for {issuer}")

    async def get(self, url: str, model: type[Document]) -> Document:
        """The JSON document at `url`, read into `model`; a redirect is not
        followed."""
        try:
            response = await self.http.get(url, follow_redirects=False)
            response.raise_for_status()
            return model.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise VerificationError("unknown_key", f"{url}: {exc}") from None
