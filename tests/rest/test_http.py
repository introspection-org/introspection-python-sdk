"""Tests for :class:`introspection_sdk._http._HttpClient`.

Driven through a real in-process ``httpx`` transport (see
``tests/rest/conftest.py``).
"""

from __future__ import annotations

import httpx
import pytest

from introspection_sdk._backoff import _is_retryable_status
from introspection_sdk._errors import (
    NetworkError,
    NotFoundError,
    RateLimitError,
    SandboxUnavailableError,
)
from introspection_sdk._http import _clean_params

from .conftest import FakeAPI


def _fails_then(
    status: int,
    ok_body: dict,
    *,
    fail_times: int,
    fail_headers: dict[str, str] | None = None,
):
    """Stateful handler: ``status`` for the first ``fail_times`` calls, then
    ``200`` with ``ok_body``."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            return httpx.Response(
                status,
                headers=fail_headers,
                json={"detail": f"transient {status}"},
            )
        return httpx.Response(200, json=ok_body)

    return handler


def _rate_limited_then(ok_body: dict, *, fail_times: int):
    """Stateful handler: ``429`` for the first ``fail_times`` calls, then
    ``200`` with ``ok_body``."""
    return _fails_then(
        429,
        ok_body,
        fail_times=fail_times,
        fail_headers={"retry-after": "0"},
    )


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


def test_get_retries_on_503_without_retry_after(fake_api: FakeAPI):
    # No ``Retry-After`` header on the 503: the retry decision is
    # status-based, the header only ever raises the backoff floor.
    fake_api.add_handler(
        "GET", "/v1/tasks/abc", _fails_then(503, {"ok": True}, fail_times=1)
    )
    http = fake_api.client(retry_base=0.0)
    assert http.request("GET", "/v1/tasks/abc") == {"ok": True}
    assert len(fake_api.requests) == 2  # initial 503 + successful retry


def test_get_retries_on_504(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", "/v1/tasks/abc", _fails_then(504, {"ok": True}, fail_times=1)
    )
    http = fake_api.client(retry_base=0.0)
    assert http.request("GET", "/v1/tasks/abc") == {"ok": True}
    assert len(fake_api.requests) == 2  # initial 504 + successful retry


def test_get_retries_on_502(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET", "/v1/tasks/abc", _fails_then(502, {"ok": True}, fail_times=1)
    )
    http = fake_api.client(retry_base=0.0)
    assert http.request("GET", "/v1/tasks/abc") == {"ok": True}
    assert len(fake_api.requests) == 2  # initial 502 + successful retry


def test_post_503_surfaces_immediately(fake_api: FakeAPI):
    # A POST may have been processed by the upstream before the gateway
    # answered 503, so it is never retried — exactly one request goes out.
    fake_api.add(
        "POST", "/v1/things", status=503, json_body={"detail": "down"}
    )
    http = fake_api.client(retry_base=0.0)
    with pytest.raises(SandboxUnavailableError):
        http.request("POST", "/v1/things", json={"name": "widget"})
    assert len(fake_api.requests) == 1


def test_get_surfaces_503_after_exhausting_retries(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/tasks/abc", status=503, json_body={})
    http = fake_api.client(max_retries=1, retry_base=0.0)
    with pytest.raises(SandboxUnavailableError):
        http.request("GET", "/v1/tasks/abc")
    assert len(fake_api.requests) == 2  # initial + 1 retry


@pytest.mark.parametrize(
    ("status", "idempotent", "retryable"),
    [
        # 429: request was rejected before processing → every method.
        (429, True, True),
        (429, False, True),
        # 502/503/504: transient gateway/upstream → GET only.
        (502, True, True),
        (502, False, False),
        (503, True, True),
        (503, False, False),
        (504, True, True),
        (504, False, False),
        # Everything else surfaces immediately.
        (500, True, False),
        (500, False, False),
        (501, True, False),
        (400, True, False),
        (404, True, False),
        (409, False, False),
        (200, True, False),
    ],
)
def test_retryable_status_policy(
    status: int, idempotent: bool, retryable: bool
):
    assert _is_retryable_status(status, idempotent) is retryable
