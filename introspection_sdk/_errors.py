"""Typed error hierarchy for the Introspection REST API.

All subclasses extend :class:`IntrospectionAPIError` and carry the
HTTP ``status_code``, optional ``request_id`` and the parsed
``body``. Use :func:`error_from_response` to translate an
``httpx.Response`` into the right subclass based on status and the
optional body ``code`` field.
"""

from __future__ import annotations

import json as _json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx2 as httpx


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
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.body = body
        #: Seconds the server asked the caller to wait, from ``Retry-After``.
        #:
        #: On the base class, not on :class:`RateLimitError` alone: the DP
        #: sends the header on a ``503`` while a sandbox is warming up, which
        #: is precisely when a caller most wants it, and that error was
        #: dropping it on the floor.
        self.retry_after = retry_after

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"code={self.code!r}, request_id={self.request_id!r})"
        )


class AuthenticationError(IntrospectionAPIError):
    """401 — missing or invalid credentials."""


class InsufficientScopeError(IntrospectionAPIError):
    """403 with ``code=insufficient_scope`` — token lacks a capability.

    Adds ``missing_capability``; everything else is forwarded, so a field
    added to the base is not silently dropped here.
    """

    def __init__(
        self,
        message: str,
        *,
        missing_capability: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
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
    """429 — caller has been rate-limited.

    ``retry_after`` comes from the base class, which every error carries.
    """


class SandboxUnavailableError(IntrospectionAPIError):
    """503 / 504 — sandbox or upstream is unavailable."""


class NetworkError(IntrospectionAPIError):
    """Transport-level failure (DNS, TCP, TLS, timeout).

    There was no response, so ``status_code`` defaults to ``0``. That
    default is the only reason this overrides ``__init__``; everything else
    is forwarded, so a field added to the base is not silently dropped here.
    """

    def __init__(
        self, message: str, *, status_code: int = 0, **kwargs: Any
    ) -> None:
        super().__init__(message, status_code=status_code, **kwargs)


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds to wait, from either RFC 9110 ``Retry-After`` form.

    The header may be a delay in seconds *or* an HTTP-date. Only the numeric
    form used to be understood, so a date-form header silently produced no
    backoff floor at all.
    """
    if not value:
        return None
    try:
        # Clamped, like the date branch below: a negative delay is not a
        # thing to wait for, and left unclamped it became a negative floor
        # in the backoff. A nonsense value means "retry now".
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delay = (parsed - datetime.now(UTC)).total_seconds()
    # A date already in the past means "retry now", not "retry in the past".
    return max(delay, 0.0)


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
        # Read for every status, not just 429: a 503 carrying `Retry-After`
        # (a sandbox still warming up) is the other case where the server
        # has told us exactly when to come back.
        "retry_after": _parse_retry_after(res.headers.get("retry-after")),
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
        return RateLimitError(message, **kwargs)
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
    "ValidationError",
    "error_from_response",
]
