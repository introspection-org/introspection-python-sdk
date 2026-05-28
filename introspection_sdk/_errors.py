"""Typed error hierarchy for the Introspection REST API.

All subclasses extend :class:`IntrospectionAPIError` and carry the
HTTP ``status_code``, optional ``request_id`` and the parsed
``body``. Use :func:`error_from_response` to translate an
``httpx.Response`` into the right subclass based on status and the
optional body ``code`` field.
"""

from __future__ import annotations

import json as _json
from typing import Any

import httpx


class IntrospectionAPIError(Exception):
    """Base HTTP error from the Introspection REST API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.body = body

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"code={self.code!r}, request_id={self.request_id!r})"
        )


class AuthenticationError(IntrospectionAPIError):
    """401 — missing or invalid credentials."""


class InsufficientScopeError(IntrospectionAPIError):
    """403 with ``code=insufficient_scope`` — token lacks a capability."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
        missing_capability: str | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code=code,
            request_id=request_id,
            body=body,
        )
        self.missing_capability = missing_capability


class RunnerExpiredError(IntrospectionAPIError):
    """401 with ``code=runner_expired`` — Runner JWT has expired."""


class NotFoundError(IntrospectionAPIError):
    """404 — resource not found."""


class ConflictError(IntrospectionAPIError):
    """409 — resource state conflict."""


class ValidationError(IntrospectionAPIError):
    """400 / 422 — request payload failed validation."""


class RateLimitError(IntrospectionAPIError):
    """429 — caller has been rate-limited."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code=code,
            request_id=request_id,
            body=body,
        )
        self.retry_after = retry_after


class SandboxUnavailableError(IntrospectionAPIError):
    """503 / 504 — sandbox or upstream is unavailable."""


class StreamError(IntrospectionAPIError):
    """SSE transport failure (malformed frames, mid-stream disconnect)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code=code,
            request_id=request_id,
            body=body,
        )


class NetworkError(IntrospectionAPIError):
    """Transport-level failure (DNS, TCP, TLS, timeout)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code=code,
            request_id=request_id,
            body=body,
        )


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def error_from_response(res: httpx.Response) -> IntrospectionAPIError:
    """Translate an HTTP error response into a typed subclass.

    Inspects the status code and the optional body ``code`` field
    (when the body is JSON) to choose the most specific subclass.
    """
    body: Any = None
    message = f"HTTP {res.status_code}"
    ct = res.headers.get("content-type", "")
    if "json" in ct:
        try:
            body = res.json()
        except (ValueError, _json.JSONDecodeError):
            body = res.text
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, str):
                message = detail
            elif isinstance(body.get("message"), str):
                message = body["message"]
    else:
        body = res.text

    code: str | None = None
    if isinstance(body, dict):
        raw_code = body.get("code")
        if isinstance(raw_code, str):
            code = raw_code

    status = res.status_code
    request_id = res.headers.get("x-request-id")

    kwargs: dict[str, Any] = {
        "status_code": status,
        "code": code,
        "request_id": request_id,
        "body": body,
    }

    if status == 401:
        if code == "runner_expired":
            return RunnerExpiredError(message, **kwargs)
        return AuthenticationError(message, **kwargs)
    if status == 403:
        if code == "insufficient_scope":
            missing: str | None = None
            if isinstance(body, dict):
                raw_missing = body.get("missing_capability")
                if isinstance(raw_missing, str):
                    missing = raw_missing
            return InsufficientScopeError(
                message, missing_capability=missing, **kwargs
            )
        return IntrospectionAPIError(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 409:
        return ConflictError(message, **kwargs)
    if status in (400, 422):
        return ValidationError(message, **kwargs)
    if status == 429:
        retry_after = _parse_retry_after(res.headers.get("retry-after"))
        return RateLimitError(message, retry_after=retry_after, **kwargs)
    if status in (503, 504):
        return SandboxUnavailableError(message, **kwargs)
    return IntrospectionAPIError(message, **kwargs)


__all__ = [
    "AuthenticationError",
    "ConflictError",
    "InsufficientScopeError",
    "IntrospectionAPIError",
    "NetworkError",
    "NotFoundError",
    "RateLimitError",
    "RunnerExpiredError",
    "SandboxUnavailableError",
    "StreamError",
    "ValidationError",
    "error_from_response",
]
