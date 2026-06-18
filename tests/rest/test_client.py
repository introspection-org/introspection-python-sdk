"""Tests for :class:`introspection_sdk.client.IntrospectionClient`.

Construction wires up the REST namespaces but issues no requests, so
these run fully offline. ``monkeypatch`` is used only to control
process environment variables (not to stub any SDK behaviour).
"""

from __future__ import annotations

import pytest

from introspection_sdk.client import IntrospectionClient
from introspection_sdk.resources import Experiments, Recipes, Runtimes


def test_explicit_args_wire_up_namespaces():
    client = IntrospectionClient(
        token="tok",
        base_api_url="https://api.example.test",
    )
    assert isinstance(client.runtimes, Runtimes)
    assert isinstance(client.experiments, Experiments)
    assert isinstance(client.recipes, Recipes)
    assert client._token == "tok"
    assert client._base_api_url == "https://api.example.test"


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
    # accepts a `project_id` kwarg nor reads INTROSPECTION_PROJECT_ID.
    monkeypatch.setenv("INTROSPECTION_PROJECT_ID", "env-proj")
    with pytest.raises(TypeError):
        IntrospectionClient(token="t", project_id="proj-9")  # type: ignore[call-arg]
    client = IntrospectionClient(token="t")
    assert not hasattr(client, "_project_id")


def test_shutdown_is_safe_to_call_twice():
    client = IntrospectionClient(token="t")
    client.shutdown()
    client.shutdown()  # best-effort, no raise
