"""Metadata and keys: `{issuer}/.well-known/{dwk}` → `jwks_uri` → JWKS
(`#metadata-documents`), cached for a bounded time."""

import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx2 as httpx

from .errors import VerificationError

T = TypeVar("T")
#: How long an issuer's keys are trusted before they are fetched again.
KEYS_TTL_SECONDS = 300
#: The least time between refetches forced by a token that failed to verify.
REFRESH_MIN_SECONDS = 30


class Discovery:
    """Fetches issuers' metadata and keys over `http`."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        ttl_seconds: int = KEYS_TTL_SECONDS,
        refresh_min_seconds: int = REFRESH_MIN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.http = http
        self._ttl = ttl_seconds
        self._refresh_min = refresh_min_seconds
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    async def metadata(self, issuer: str, dwk: str) -> dict[str, Any]:
        """The issuer's metadata document, which must name it as `issuer`."""
        document = await self.get_json(f"{issuer}/.well-known/{dwk}")
        if str(document.get("issuer", "")).rstrip("/") != issuer:
            raise VerificationError(
                "issuer_mismatch", "metadata names another issuer"
            )
        return document

    async def jwks(
        self, issuer: str, dwk: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        """The issuer's keys; `refresh` fetches again keys that failed, since an
        issuer may rotate a key, but no more often than `refresh_min_seconds`."""
        cached = self._cache.get((issuer, dwk))
        now = self._clock()
        if cached and cached[0] > now:
            fetched_at = cached[0] - self._ttl
            if not refresh or now - fetched_at < self._refresh_min:
                return cached[1]
        document = await self.metadata(issuer, dwk)
        keys = await self.get_json(str(document.get("jwks_uri", "")))
        self._cache[(issuer, dwk)] = (self._clock() + self._ttl, keys)
        return keys

    async def verified(
        self, issuer: str, dwk: str, check: Callable[[dict[str, Any]], T]
    ) -> T:
        """`check` against the issuer's keys, and once more against fresh ones."""
        try:
            return check(await self.jwks(issuer, dwk))
        except VerificationError:
            return check(await self.jwks(issuer, dwk, refresh=True))

    async def key(self, issuer: str, dwk: str, kid: str) -> dict[str, Any]:
        """One published key, by `kid`: how a `jwks_uri` signature is resolved."""
        for refresh in (False, True):
            keys = await self.jwks(issuer, dwk, refresh=refresh)
            for key in keys.get("keys", []):
                if isinstance(key, dict) and key.get("kid") == kid:
                    return key
        raise VerificationError("unknown_key", f"no key {kid} for {issuer}")

    async def get_json(self, url: str) -> dict[str, Any]:
        try:
            response = await self.http.get(url)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VerificationError("unknown_key", f"{url}: {exc}") from None
        if not isinstance(document, dict):
            raise VerificationError(
                "unknown_key", f"{url} is not a JSON object"
            )
        return document
