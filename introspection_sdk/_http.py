"""Small HTTP clients used by the REST API namespaces.

:class:`_HttpClient` wraps ``httpx.Client`` and :class:`_AsyncHttpClient`
wraps ``httpx.AsyncClient``; both centralise base-URL joining,
``Authorization`` header injection, error translation, and SSE
streaming. Kept private so the public surface stays the REST namespace
classes themselves. The two clients are kept deliberately symmetric so
the sync and async resource namespaces can mirror each other line for
line.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

import httpx

from introspection_sdk._errors import (
    NetworkError,
    _parse_retry_after,
    error_from_response,
)
from introspection_sdk._retry import backoff_delay

#: Default automatic retries on a ``429 Too Many Requests`` for unary REST
#: calls (honouring ``Retry-After``). ``0`` disables retrying. Streaming has
#: its own resume budget (see :mod:`introspection_sdk.resumable`).
DEFAULT_MAX_RETRIES = 2
#: Default base step (seconds) of the capped-exponential ``429`` retry backoff.
DEFAULT_RETRY_BASE = 0.5

#: Transient gateway/upstream statuses retried only for idempotent (GET) calls.
_IDEMPOTENT_RETRY_STATUSES = frozenset({502, 503, 504})


def _should_retry(status: int, method: str) -> bool:
    """Whether a non-2xx status is worth retrying.

    ``429`` is retried for any method (the request was rejected and never
    processed, so re-sending is side-effect-safe even for writes); transient
    gateway/upstream errors (``502``/``503``/``504``) are retried only for
    idempotent ``GET`` requests.
    """
    if status == 429:
        return True
    if status in _IDEMPOTENT_RETRY_STATUSES:
        return method.upper() == "GET"
    return False


class _HttpClient:
    """Thin wrapper around ``httpx.Client`` for REST calls.

    Used both for the CP-facing client (on ``IntrospectionClient``)
    and for the DP-facing client (on a ``Runner``). The two only
    differ in their base URL and bearer token.
    """

    def __init__(
        self,
        *,
        api_url: str,
        token: str,
        additional_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base: float = DEFAULT_RETRY_BASE,
    ) -> None:
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )
        self._auth_headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
        }
        if additional_headers:
            self._auth_headers.update(additional_headers)
        self._max_retries = max_retries
        self._retry_base = retry_base

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        expect: str = "json",
    ) -> Any:
        headers = dict(self._auth_headers)
        # Auto-retry transient statuses, honouring ``Retry-After`` as a backoff
        # floor: ``429`` for any method (rejected, not processed), and
        # ``502``/``503``/``504`` for idempotent GETs only (see
        # ``_should_retry``). Multipart uploads aren't retried.
        retries = 0 if files is not None else self._max_retries
        attempt = 0
        while True:
            try:
                res = self._client.request(
                    method,
                    path,
                    params=_clean_params(params),
                    json=json,
                    files=files,
                    data=data,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc
            if _should_retry(res.status_code, method) and attempt < retries:
                delay = backoff_delay(
                    attempt,
                    _parse_retry_after(res.headers.get("retry-after")),
                    self._retry_base,
                )
                attempt += 1
                time.sleep(delay)
                continue
            if res.status_code >= 400:
                raise error_from_response(res)
            if expect == "empty":
                return None
            if expect == "bytes":
                return res.content
            return res.json()

    def stream_bytes(self, path: str) -> Iterator[bytes]:
        try:
            with self._client.stream(
                "GET", path, headers=self._auth_headers
            ) as res:
                if res.status_code >= 400:
                    res.read()
                    raise error_from_response(res)
                yield from res.iter_bytes()
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc

    def stream_sse_lines(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[str]:
        req_headers = dict(self._auth_headers)
        req_headers["Accept"] = "text/event-stream"
        if headers:
            req_headers.update(headers)
        try:
            with self._client.stream(
                "GET", path, params=_clean_params(params), headers=req_headers
            ) as res:
                if res.status_code >= 400:
                    res.read()
                    raise error_from_response(res)
                yield from res.iter_lines()
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc


class _AsyncHttpClient:
    """Thin wrapper around ``httpx.AsyncClient`` for REST calls.

    The async twin of :class:`_HttpClient`. Used both for the CP-facing
    client (on ``AsyncIntrospectionClient``) and for the DP-facing
    client (on an ``AsyncRunner``). The two only differ in their base
    URL and bearer token.
    """

    def __init__(
        self,
        *,
        api_url: str,
        token: str,
        additional_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base: float = DEFAULT_RETRY_BASE,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )
        self._auth_headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
        }
        if additional_headers:
            self._auth_headers.update(additional_headers)
        self._max_retries = max_retries
        self._retry_base = retry_base

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        expect: str = "json",
    ) -> Any:
        headers = dict(self._auth_headers)
        # See the sync twin: transparent retry of ``429`` (any method) and
        # ``502``/``503``/``504`` (GET only), honouring ``Retry-After``;
        # multipart uploads are excluded.
        retries = 0 if files is not None else self._max_retries
        attempt = 0
        while True:
            try:
                res = await self._client.request(
                    method,
                    path,
                    params=_clean_params(params),
                    json=json,
                    files=files,
                    data=data,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise NetworkError(str(exc)) from exc
            if _should_retry(res.status_code, method) and attempt < retries:
                delay = backoff_delay(
                    attempt,
                    _parse_retry_after(res.headers.get("retry-after")),
                    self._retry_base,
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue
            if res.status_code >= 400:
                raise error_from_response(res)
            if expect == "empty":
                return None
            if expect == "bytes":
                return res.content
            return res.json()

    async def stream_bytes(self, path: str) -> AsyncIterator[bytes]:
        try:
            async with self._client.stream(
                "GET", path, headers=self._auth_headers
            ) as res:
                if res.status_code >= 400:
                    await res.aread()
                    raise error_from_response(res)
                async for chunk in res.aiter_bytes():
                    yield chunk
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc

    async def stream_sse_lines(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[str]:
        req_headers = dict(self._auth_headers)
        req_headers["Accept"] = "text/event-stream"
        if headers:
            req_headers.update(headers)
        try:
            async with self._client.stream(
                "GET", path, params=_clean_params(params), headers=req_headers
            ) as res:
                if res.status_code >= 400:
                    await res.aread()
                    raise error_from_response(res)
                async for line in res.aiter_lines():
                    yield line
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc


def _clean_params(
    params: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if params is None:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        out[k] = v
    return out
