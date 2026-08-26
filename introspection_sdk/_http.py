"""Small HTTP clients used by the REST API namespaces.

:class:`_HttpClient` wraps ``httpx.Client`` and :class:`_AsyncHttpClient`
wraps ``httpx.AsyncClient``; both centralise base-URL joining,
``Authorization`` header injection, error translation, and SSE
streaming. Kept private so the public surface stays the REST namespace
classes themselves.

``httpx`` throughout this package is ``httpx2`` under an alias --- the
Pydantic-maintained successor, which the OpenAI, Anthropic and MCP SDKs are
also built on. Callers passing their own ``transport=`` must pass an httpx2
one; see docs/advanced.md. The two clients are kept deliberately symmetric so
the sync and async resource namespaces can mirror each other line for
line.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx2 as httpx

from introspection_sdk._backoff import _is_retryable_status, _retry_delay
from introspection_sdk._errors import (
    NetworkError,
    RunnerExpiredError,
    _parse_retry_after,
    error_from_response,
)

#: Default automatic retries for unary REST calls: ``429`` on every method,
#: ``502``/``503``/``504`` on ``GET`` only (see
#: :func:`introspection_sdk._backoff._is_retryable_status`). ``Retry-After``
#: is honoured as a backoff floor when present. ``0`` disables retrying.
#: Streaming has its own resume budget (see
#: :mod:`introspection_sdk.resumable`).
DEFAULT_MAX_RETRIES = 2
#: Default base step (seconds) of the capped-exponential retry backoff.
DEFAULT_RETRY_BASE = 0.5


@dataclass(frozen=True)
class RawResponse:
    """A raw response body plus headers, returned by ``request(expect="raw")``.

    Used by the Arrow list-read path, where the row values arrive in the
    columnar body and pagination metadata (``X-Next-Cursor`` /
    ``X-Result-Count`` / ``X-Truncated`` / ``X-Total-Count``) moves to
    response headers. Keeps ``httpx`` off the resource layer's surface.
    """

    content: bytes
    headers: Mapping[str, str]


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
        cp_session: str | None = None,
        additional_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base: float = DEFAULT_RETRY_BASE,
    ) -> None:
        self._closed = False
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )
        self._auth_headers: dict[str, str] = (
            {"Cookie": f"intro_cp_session={cp_session}"}
            if cp_session
            else {"Authorization": f"Bearer {token}"}
        )
        if additional_headers:
            self._auth_headers.update(additional_headers)
        self._max_retries = max_retries
        self._retry_base = retry_base

    def close(self) -> None:
        self._closed = True
        self._client.close()

    def _check_open(self) -> None:
        """Raise a typed error once this client has been closed.

        ``Runner.refresh()`` closes the client it replaces, and
        ``Runner.close()`` closes the live one, but a namespace handle the
        caller already holds keeps a reference to it. Without this the next
        call surfaced httpx's bare ``RuntimeError: Cannot send a request, as
        the client has been closed``, bypassing the typed-error guarantee
        ``_check_open`` on the Runner exists to give.
        """
        if self._closed:
            raise RunnerExpiredError(
                "This client has been closed (the Runner was closed or "
                "refreshed); take a fresh namespace handle from the Runner.",
                status_code=0,
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        expect: str = "json",
    ) -> Any:
        self._check_open()
        req_headers = dict(self._auth_headers)
        if headers:
            req_headers.update(headers)
        headers = req_headers
        # Auto-retry retryable statuses, honouring ``Retry-After`` as a
        # backoff floor when present: ``429`` on any method (the request was
        # rejected and never processed, so retrying is side-effect-safe for
        # writes too) and ``502``/``503``/``504`` on idempotent ``GET`` calls
        # only. Multipart uploads aren't retried.
        retries = 0 if files is not None else self._max_retries
        idempotent = method.upper() == "GET"
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
            if (
                _is_retryable_status(res.status_code, idempotent)
                and attempt < retries
            ):
                delay = _retry_delay(
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
            if expect == "raw":
                return RawResponse(content=res.content, headers=res.headers)
            return res.json()

    def stream_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[bytes]:
        req_headers = dict(self._auth_headers)
        if headers:
            req_headers.update(headers)
        try:
            with self._client.stream(
                "GET",
                path,
                params=_clean_params(params),
                headers=req_headers,
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
        self._check_open()
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
        cp_session: str | None = None,
        additional_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base: float = DEFAULT_RETRY_BASE,
    ) -> None:
        self._closed = False
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )
        self._auth_headers: dict[str, str] = (
            {"Cookie": f"intro_cp_session={cp_session}"}
            if cp_session
            else {"Authorization": f"Bearer {token}"}
        )
        if additional_headers:
            self._auth_headers.update(additional_headers)
        self._max_retries = max_retries
        self._retry_base = retry_base

    async def aclose(self) -> None:
        self._closed = True
        await self._client.aclose()

    def _check_open(self) -> None:
        """Async twin of :meth:`_HttpClient._check_open`."""
        if self._closed:
            raise RunnerExpiredError(
                "This client has been closed (the Runner was closed or "
                "refreshed); take a fresh namespace handle from the Runner.",
                status_code=0,
            )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        expect: str = "json",
    ) -> Any:
        self._check_open()
        req_headers = dict(self._auth_headers)
        if headers:
            req_headers.update(headers)
        headers = req_headers
        # See the sync twin: transparent retry on ``429`` (any method) and
        # ``502``/``503``/``504`` (``GET`` only), honouring ``Retry-After``
        # as a backoff floor; multipart uploads are excluded.
        retries = 0 if files is not None else self._max_retries
        idempotent = method.upper() == "GET"
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
            if (
                _is_retryable_status(res.status_code, idempotent)
                and attempt < retries
            ):
                delay = _retry_delay(
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
            if expect == "raw":
                return RawResponse(content=res.content, headers=res.headers)
            return res.json()

    async def stream_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[bytes]:
        req_headers = dict(self._auth_headers)
        if headers:
            req_headers.update(headers)
        try:
            async with self._client.stream(
                "GET",
                path,
                params=_clean_params(params),
                headers=req_headers,
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
        self._check_open()
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
        out[k] = _param_value(v)
    return out


def _param_value(value: Any) -> Any:
    """Render one query-parameter value the way the API expects it.

    ``httpx`` falls back to ``str()`` for anything it does not know, and
    ``str(datetime)`` is the space-separated form ``2025-01-01 12:30:00+00:00``
    -- not ISO-8601. The window parameters (``start`` / ``end`` /
    ``start_date`` / ``end_date``, and the ``start_date`` a ``lookback``
    resolves to) accept ``datetime`` by design, so every one of them went out
    malformed. ``isoformat()`` puts the ``T`` back.
    """
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_param_value(item) for item in value]
    return value
