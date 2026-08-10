"""Unit tests for the typed error hierarchy and ``error_from_response``.

Pure logic over real :class:`httpx.Response` objects — no transport,
no mocks.
"""

from __future__ import annotations

import httpx
import pytest

from introspection_sdk._errors import (
    AuthenticationError,
    ConflictError,
    InsufficientScopeError,
    IntrospectionAPIError,
    NotFoundError,
    RateLimitError,
    RunnerExpiredError,
    SandboxUnavailableError,
    ValidationError,
    error_from_response,
)


def _response(
    status: int,
    *,
    json_body: object | None = None,
    text: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    if json_body is not None:
        return httpx.Response(status, json=json_body, headers=headers)
    return httpx.Response(status, text=text or "", headers=headers)


def test_401_maps_to_authentication_error():
    err = error_from_response(
        _response(401, json_body={"detail": "bad token"})
    )
    assert isinstance(err, AuthenticationError)
    assert err.status_code == 401
    assert str(err) == "bad token"


def test_401_runner_expired_maps_to_runner_expired_error():
    err = error_from_response(
        _response(401, json_body={"code": "runner_expired"})
    )
    assert isinstance(err, RunnerExpiredError)
    assert err.code == "runner_expired"


def test_403_insufficient_scope_carries_missing_capability():
    err = error_from_response(
        _response(
            403,
            json_body={
                "code": "insufficient_scope",
                "missing_capability": "tasks:delete",
                "message": "nope",
            },
        )
    )
    assert isinstance(err, InsufficientScopeError)
    assert err.missing_capability == "tasks:delete"
    assert str(err) == "nope"


def test_403_plain_is_base_error():
    err = error_from_response(_response(403, json_body={"detail": "denied"}))
    assert type(err) is IntrospectionAPIError
    assert err.status_code == 403


def test_404_maps_to_not_found():
    err = error_from_response(_response(404, json_body={"detail": "gone"}))
    assert isinstance(err, NotFoundError)


def test_409_maps_to_conflict():
    assert isinstance(
        error_from_response(_response(409, json_body={})), ConflictError
    )


@pytest.mark.parametrize("status", [400, 422])
def test_400_and_422_map_to_validation_error(status: int):
    assert isinstance(
        error_from_response(_response(status, json_body={})), ValidationError
    )


def test_429_parses_retry_after_header():
    err = error_from_response(
        _response(429, json_body={}, headers={"retry-after": "12.5"})
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 12.5


def test_429_with_invalid_retry_after_is_none():
    err = error_from_response(
        _response(429, json_body={}, headers={"retry-after": "soon"})
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after is None


def test_every_error_carries_retry_after_not_just_429():
    """A 503 is when `Retry-After` matters most.

    It lived on `RateLimitError` alone, so a sandbox still warming up told
    the caller exactly when to come back and the SDK dropped it.
    """
    err = error_from_response(
        _response(503, json_body={}, headers={"retry-after": "120"})
    )
    assert isinstance(err, SandboxUnavailableError)
    assert err.retry_after == 120.0

    # And it is simply absent when the server sent no header.
    assert (
        error_from_response(_response(404, json_body={})).retry_after is None
    )


@pytest.mark.parametrize("status", [503, 504])
def test_5xx_maps_to_sandbox_unavailable(status: int):
    assert isinstance(
        error_from_response(_response(status, json_body={})),
        SandboxUnavailableError,
    )


def test_unmapped_status_falls_back_to_base_error():
    err = error_from_response(_response(418, json_body={"detail": "teapot"}))
    assert type(err) is IntrospectionAPIError
    assert err.status_code == 418


def test_non_json_body_is_captured_as_text():
    err = error_from_response(
        _response(500, text="boom", headers={"content-type": "text/plain"})
    )
    assert err.body == "boom"
    assert err.status_code == 500


def test_request_id_header_is_propagated():
    err = error_from_response(
        _response(404, json_body={}, headers={"x-request-id": "req-42"})
    )
    assert err.request_id == "req-42"


def test_malformed_json_body_falls_back_to_text():
    res = httpx.Response(
        400,
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    err = error_from_response(res)
    assert isinstance(err, ValidationError)
    assert err.body == "{not json"


def test_message_field_used_when_no_detail():
    err = error_from_response(
        _response(409, json_body={"message": "state conflict"})
    )
    assert str(err) == "state conflict"


def test_repr_includes_status_and_code():
    err = error_from_response(
        _response(401, json_body={"code": "runner_expired"})
    )
    text = repr(err)
    assert "RunnerExpiredError" in text
    assert "status_code=401" in text


def test_a_negative_retry_after_means_now_not_a_negative_delay():
    """A negative delay is clamped.

    Unclamped it became a negative floor in the backoff, and then a
    negative sleep.
    """
    err = error_from_response(
        _response(429, json_body={}, headers={"retry-after": "-5"})
    )
    assert err.retry_after == 0.0
