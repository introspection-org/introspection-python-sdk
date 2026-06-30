"""Tests for :class:`introspection_sdk._http._HttpClient`.

Driven through a real in-process ``httpx`` transport (see
``tests/rest/conftest.py``).
"""

from __future__ import annotations

import httpx
import pytest

from introspection_sdk._errors import (
    NetworkError,
    NotFoundError,
    RateLimitError,
)
from introspection_sdk._http import _clean_params

from .conftest import FakeAPI


def _rate_limited_then(ok_body: dict, *, fail_times: int):
    """Stateful handler: ``429`` for the first ``fail_times`` calls, then
    ``200`` with ``ok_body``."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"detail": "rate limited"},
            )
        return httpx.Response(200, json=ok_body)

    return handler


def test_request_returns_parsed_json(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/ping", json_body={"ok": True})
    http = fake_api.client()
    assert http.request("GET", "/v1/ping") == {"ok": True}


def test_authorization_and_additional_headers_are_sent(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/ping", json_body={})
    http = fake_api.client(
        token="secret", additional_headers={"x-trace": "abc"}
    )
    http.request("GET", "/v1/ping")
    sent = fake_api.last_request.headers
    assert sent["authorization"] == "Bearer secret"
    assert sent["x-trace"] == "abc"


def test_none_query_params_are_dropped(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/things", json_body={})
    http = fake_api.client()
    http.request(
        "GET", "/v1/things", params={"a": "1", "b": None, "limit": 50}
    )
    params = fake_api.last_request.params
    assert params.get("a") == "1"
    assert "b" not in params
    assert params.get("limit") == "50"


def test_json_body_is_forwarded(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/things", json_body={"id": "x"})
    http = fake_api.client()
    http.request("POST", "/v1/things", json={"name": "widget"})
    assert fake_api.last_request.json() == {"name": "widget"}


def test_expect_empty_returns_none(fake_api: FakeAPI):
    fake_api.add("DELETE", "/v1/things/1", status=204)
    http = fake_api.client()
    assert http.request("DELETE", "/v1/things/1", expect="empty") is None


def test_expect_bytes_returns_raw_content(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/blob", content=b"\x00\x01\x02")
    http = fake_api.client()
    assert http.request("GET", "/v1/blob", expect="bytes") == b"\x00\x01\x02"


def test_error_status_raises_typed_error(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/missing", status=404, json_body={"detail": "x"})
    http = fake_api.client()
    with pytest.raises(NotFoundError):
        http.request("GET", "/v1/missing")


def test_transport_error_is_wrapped_as_network_error(fake_api: FakeAPI):
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    fake_api.add_handler("GET", "/v1/down", _boom)
    http = fake_api.client()
    with pytest.raises(NetworkError):
        http.request("GET", "/v1/down")


def test_stream_bytes_yields_chunks(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/download", content=b"chunked-bytes")
    http = fake_api.client()
    assert b"".join(http.stream_bytes("/v1/download")) == b"chunked-bytes"


def test_stream_bytes_raises_typed_error_on_4xx(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/download", status=404, json_body={})
    http = fake_api.client()
    with pytest.raises(NotFoundError):
        list(http.stream_bytes("/v1/download"))


def test_stream_bytes_wraps_transport_error(fake_api: FakeAPI):
    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("reset")

    fake_api.add_handler("GET", "/v1/download", _boom)
    http = fake_api.client()
    with pytest.raises(NetworkError):
        list(http.stream_bytes("/v1/download"))


def test_stream_sse_lines_yields_lines_and_sets_accept(fake_api: FakeAPI):
    body = "event: text\ndata: hi\n\n"
    fake_api.add("GET", "/v1/stream", content=body.encode())
    http = fake_api.client()
    lines = list(http.stream_sse_lines("/v1/stream"))
    assert "event: text" in lines
    assert "data: hi" in lines
    assert fake_api.last_request.headers["accept"] == "text/event-stream"


def test_stream_sse_lines_raises_typed_error_on_4xx(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/stream", status=404, json_body={})
    http = fake_api.client()
    with pytest.raises(NotFoundError):
        list(http.stream_sse_lines("/v1/stream"))


def test_close_is_idempotent(fake_api: FakeAPI):
    http = fake_api.client()
    http.close()
    http.close()  # no raise


def test_clean_params_returns_none_for_none():
    assert _clean_params(None) is None


def test_request_retries_on_429_then_succeeds(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", "/v1/tasks/abc", _rate_limited_then({"ok": True}, fail_times=1)
    )
    http = fake_api.client(retry_base=0.0)
    assert http.request("GET", "/v1/tasks/abc") == {"ok": True}
    # Initial 429 + the retry that succeeded.
    assert len(fake_api.requests) == 2


def test_request_surfaces_rate_limit_after_exhausting(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tasks/def",
        status=429,
        headers={"retry-after": "0"},
        json_body={"detail": "rate limited"},
    )
    http = fake_api.client(max_retries=1, retry_base=0.0)
    with pytest.raises(RateLimitError):
        http.request("GET", "/v1/tasks/def")
    assert len(fake_api.requests) == 2  # initial + 1 retry


def test_request_does_not_retry_when_disabled(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tasks/ghi",
        status=429,
        headers={"retry-after": "0"},
        json_body={"detail": "rate limited"},
    )
    http = fake_api.client(max_retries=0)
    with pytest.raises(RateLimitError):
        http.request("GET", "/v1/tasks/ghi")
    assert len(fake_api.requests) == 1  # no retry
