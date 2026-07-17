"""Runtime runner creation contract tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from introspection_sdk.client import IntrospectionClient
from introspection_sdk.runner import Runner

from .conftest import (
    RUNTIME_ID,
    FakeAPI,
    paginated,
    runner_spec_payload,
    runtime_payload,
)


def _client(fake_api: FakeAPI) -> IntrospectionClient:
    client = IntrospectionClient(token="test", base_api_url="https://api.test")
    client._http.close()
    client._http = fake_api.client()
    client._runtimes._http = client._http
    client._experiments._http = client._http
    return client


def test_runtime_run_resolves_then_forwards_current_contract(
    fake_api: FakeAPI,
):
    runtime_group_id = UUID("33333333-3333-3333-3333-333333333333")
    fake_api.add(
        "GET", "/v1/runtimes", json_body=paginated([runtime_payload()])
    )
    fake_api.add(
        "POST",
        f"/v1/runtimes/{RUNTIME_ID}/run",
        json_body=runner_spec_payload(),
    )

    runner = (
        _client(fake_api)
        .runtime(runtime_group_id)
        .run(
            identity={"user_id": "u1"},
            caller={"locale": "en-US"},
            agent_name="support",
            ttl_seconds=900,
            scope="tasks:read tasks:write",
        )
    )

    assert isinstance(runner, Runner)
    assert [request.path for request in fake_api.requests] == [
        "/v1/runtimes",
        f"/v1/runtimes/{RUNTIME_ID}/run",
    ]
    assert fake_api.requests[0].params.get("runtime") == str(runtime_group_id)
    assert "only_active" not in fake_api.requests[0].params
    assert fake_api.last_request.json() == {
        "identity": {"user_id": "u1"},
        "caller": {"locale": "en-US"},
        "agent_name": "support",
        "ttl_seconds": 900,
        "scope": "tasks:read tasks:write",
    }
    assert runner.context.runtime_group_id is not None
    assert runner.context.recipe_repository_id is not None
    assert runner.context.agent_name == "agent"


def test_runtime_not_found_and_ambiguous(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/runtimes", json_body=paginated([]))
    with pytest.raises(LookupError, match="No runtime"):
        _client(fake_api).runtime("missing").run()

    fake_api.add(
        "GET",
        "/v1/runtimes",
        json_body=paginated([runtime_payload(), runtime_payload()]),
    )
    with pytest.raises(LookupError, match="Ambiguous runtime"):
        _client(fake_api).runtime("duplicate").run()
