"""INTROSPECTION_DEV_TARGET — how an app names the `introspection dev`
server its tasks should reach.

Construction wires the header onto every namespace but issues no requests, so
these run fully offline. ``monkeypatch`` is used only to control process
environment variables, never to stub SDK behaviour.
"""

from __future__ import annotations

import pytest

from introspection_sdk.client import (
    AsyncIntrospectionClient,
    IntrospectionClient,
)
from introspection_sdk.dev_target import (
    DEV_TARGET_ENV,
    DEV_TARGET_HEADER,
    dev_target_headers,
    resolve_dev_target,
)


def test_resolves_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEV_TARGET_ENV, "roland")
    assert resolve_dev_target() == "roland"


def test_is_trimmed_and_blank_is_the_same_as_unset(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(DEV_TARGET_ENV, "  roland  ")
    assert resolve_dev_target() == "roland"

    monkeypatch.setenv(DEV_TARGET_ENV, "   ")
    assert resolve_dev_target() is None

    monkeypatch.delenv(DEV_TARGET_ENV, raising=False)
    assert resolve_dev_target() is None


def test_no_local_username_fallback(monkeypatch: pytest.MonkeyPatch):
    """Env-only on purpose.

    Defaulting to the local username is zero-config on a laptop and wrong
    elsewhere: a process in a shared development deployment running as ``app``
    would name a machine nobody serves and fail closed, where today it reaches
    the one connected dev server. The CLI defaults to the username because it
    names *itself*; this names someone else's machine and can run anywhere.
    """
    monkeypatch.delenv(DEV_TARGET_ENV, raising=False)
    assert resolve_dev_target() is None
    assert dev_target_headers(None) is None


def test_merges_under_caller_supplied_headers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEV_TARGET_ENV, "roland")

    assert dev_target_headers(None) == {DEV_TARGET_HEADER: "roland"}
    assert dev_target_headers({"X-Trace": "1"}) == {
        DEV_TARGET_HEADER: "roland",
        "X-Trace": "1",
    }
    # An explicitly configured header is more specific than an env var.
    assert dev_target_headers({DEV_TARGET_HEADER: "explicit"}) == {
        DEV_TARGET_HEADER: "explicit"
    }


def test_unset_leaves_headers_untouched(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEV_TARGET_ENV, raising=False)

    assert dev_target_headers(None) is None
    assert dev_target_headers({"X-Trace": "1"}) == {"X-Trace": "1"}


@pytest.mark.parametrize(
    "client_cls", [IntrospectionClient, AsyncIntrospectionClient]
)
def test_client_carries_the_header_on_every_namespace(
    client_cls, monkeypatch: pytest.MonkeyPatch
):
    """Every namespace, because the path this exists for is a task call.

    A bare ``POST /v1/tasks`` with a dev API key has no runner claim to carry a
    target — the JWT is minted from the key row — so the header has to be on
    the client rather than on one request shape.
    """
    monkeypatch.setenv(DEV_TARGET_ENV, "roland")

    client = client_cls(token="t")

    assert client._additional_headers[DEV_TARGET_HEADER] == "roland"


def test_client_unset_carries_no_target(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(DEV_TARGET_ENV, raising=False)

    # The client always carries its own `User-Agent`, so the assertion is
    # that no *target* was added, not that the header set is empty.
    headers = IntrospectionClient(token="t")._additional_headers
    assert DEV_TARGET_HEADER not in (headers or {})


def test_non_ascii_and_spaced_targets_are_percent_encoded(monkeypatch) -> None:
    """httpx raises on a non-ASCII header value, so encoding is what lets a
    login name like `andré` route rather than fail the request.

    Safe because the Data Plane decodes before it normalizes, so this lands on
    the same target as the `--as andré` the CLI advertises over protobuf.
    """
    monkeypatch.setenv(DEV_TARGET_ENV, "andré")
    assert resolve_dev_target() == "andr%C3%A9"

    monkeypatch.setenv(DEV_TARGET_ENV, "roland laptop")
    assert resolve_dev_target() == "roland%20laptop"

    # The ordinary case is untouched.
    monkeypatch.setenv(DEV_TARGET_ENV, "roland")
    assert resolve_dev_target() == "roland"


def test_encodes_exactly_as_the_node_and_rust_clients_do(monkeypatch) -> None:
    """One target must put identical bytes on the wire from any SDK.

    The unreserved set has to survive untouched — an everyday `my-laptop`
    arriving as `my%2Dlaptop` from one client and not another is a debugging
    trap, even though the Data Plane decodes before it normalizes and would
    route either.
    """
    for raw, wire in [
        ("my-laptop", "my-laptop"),
        ("roland_box", "roland_box"),
        ("host.local", "host.local"),
        ("a~b", "a~b"),
        ("c!d", "c%21d"),
        ("e(f)", "e%28f%29"),
        ("andré", "andr%C3%A9"),
        ("my laptop", "my%20laptop"),
    ]:
        monkeypatch.setenv(DEV_TARGET_ENV, raw)
        assert resolve_dev_target() == wire


def test_encoded_target_survives_an_httpx_request(monkeypatch) -> None:
    """The reason the encoding exists, asserted against the client that
    rejected the raw value."""
    import httpx

    monkeypatch.setenv(DEV_TARGET_ENV, "andré")
    headers = dev_target_headers(None)
    assert headers is not None
    request = httpx.Request(
        "POST", "http://example.invalid/v1/tasks", headers=headers
    )
    assert request.headers[DEV_TARGET_HEADER] == "andr%C3%A9"
