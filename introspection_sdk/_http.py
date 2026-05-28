"""Small synchronous HTTP client used by the REST API namespaces.

Wraps ``httpx.Client`` to centralise base-URL joining, ``Authorization``
header injection, error translation, and SSE streaming. Kept private
so the public surface stays the REST namespace classes themselves.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import httpx

from introspection_sdk._errors import NetworkError, error_from_response


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

    def stream_sse_lines(self, path: str) -> Iterator[str]:
        headers = dict(self._auth_headers)
        headers["Accept"] = "text/event-stream"
        try:
            with self._client.stream("GET", path, headers=headers) as res:
                if res.status_code >= 400:
                    res.read()
                    raise error_from_response(res)
                yield from res.iter_lines()
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
