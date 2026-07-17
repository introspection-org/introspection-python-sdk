"""Tests for :class:`introspection_sdk.client.IntrospectionClient`.

Construction wires up the REST namespaces but issues no requests, so
these run fully offline. ``monkeypatch`` is used only to control
process environment variables (not to stub any SDK behaviour).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from introspection_sdk.client import (
    AsyncIntrospectionClient,
    IntrospectionClient,
)
from introspection_sdk.resources import (
    AsyncExperimentHandle,
    AsyncRuntimeHandle,
    ExperimentHandle,
    RuntimeHandle,
)


class _RaisingHttp:
    """Fake HTTP client whose close raises — exercises the best-effort
    cleanup branch in ``shutdown`` without patching SDK internals."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True
        raise RuntimeError("close boom")

    async def aclose(self) -> None:
        self.closed = True
        raise RuntimeError("aclose boom")


def test_explicit_args_expose_only_runner_openers():
    client = IntrospectionClient(
        token="tok",
        base_api_url="https://api.example.test",
    )
    assert isinstance(client.runtime("agent"), RuntimeHandle)
    assert isinstance(client.experiment(UUID(int=1)), ExperimentHandle)
    assert not hasattr(client, "runtimes")
    assert not hasattr(client, "experiments")
    assert not hasattr(client, "recipes")
    assert client._token == "tok"
    assert client._base_api_url == "https://api.example.test"


def test_async_client_exposes_only_runner_openers():
    client = AsyncIntrospectionClient(token="tok")
    assert isinstance(client.runtime("agent"), AsyncRuntimeHandle)
    assert isinstance(
        client.experiment(UUID(int=1)),
        AsyncExperimentHandle,
    )
    assert not hasattr(client, "runtimes")
    assert not hasattr(client, "experiments")
    assert not hasattr(client, "recipes")


def test_defaults_come_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTROSPECTION_TOKEN", "env-token")
    monkeypatch.delenv("INTROSPECTION_BASE_API_URL", raising=False)
    client = IntrospectionClient()
    assert client._token == "env-token"
    assert client._base_api_url == "https://api.introspection.dev"


def test_base_url_override_from_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("INTROSPECTION_BASE_API_URL", "https://custom.test")
    client = IntrospectionClient(token="x")
    assert client._base_api_url == "https://custom.test"


def test_project_is_not_a_client_option(monkeypatch: pytest.MonkeyPatch):
    # The project is scoped by the API key server-side — the client neither
    # accepts a `project_id` kwarg nor reads an ambient project selector.
    monkeypatch.setenv("INTROSPECTION_PROJECT", "env-proj")
    with pytest.raises(TypeError):
        IntrospectionClient(token="t", project_id="proj-9")  # type: ignore[call-arg]
    client = IntrospectionClient(token="t")
    assert not hasattr(client, "_project_id")


def test_shutdown_is_safe_to_call_twice():
    client = IntrospectionClient(token="t")
    client.shutdown()
    client.shutdown()  # best-effort, no raise


def test_shutdown_swallows_close_errors():
    client = IntrospectionClient(token="t")
    raising = _RaisingHttp()
    client._http = raising
    client.shutdown()  # best-effort: the close error is swallowed
    assert raising.closed


@pytest.mark.asyncio
async def test_async_shutdown_swallows_close_errors():
    client = AsyncIntrospectionClient(token="t")
    raising = _RaisingHttp()
    client._http = raising
    await client.shutdown()  # best-effort: the aclose error is swallowed
    assert raising.closed


@pytest.mark.asyncio
async def test_async_context_manager_shuts_down_on_exit():
    async with AsyncIntrospectionClient(token="t") as client:
        assert isinstance(client, AsyncIntrospectionClient)
        client._http = _RaisingHttp()
    # Exiting the block calls shutdown(); the close error is swallowed.
