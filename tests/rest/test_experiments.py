"""Experiment runner creation contract tests."""

from __future__ import annotations

from uuid import UUID

from introspection_sdk.client import IntrospectionClient
from introspection_sdk.runner import Runner

from .conftest import EXPERIMENT_ID, FakeAPI, runner_spec_payload


def test_experiment_run_forwards_current_contract(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/run",
        json_body=runner_spec_payload(),
    )
    client = IntrospectionClient(token="test", base_api_url="https://api.test")
    client._http.close()
    client._http = fake_api.client()
    client._experiments._http = client._http

    runner = client.experiment(UUID(EXPERIMENT_ID)).run(
        identity={"user_id": "u2"},
        agent_name="researcher",
        scope="tasks:read tasks:write",
    )

    assert isinstance(runner, Runner)
    assert fake_api.last_request.path == f"/v1/experiments/{EXPERIMENT_ID}/run"
    assert fake_api.last_request.json() == {
        "identity": {"user_id": "u2"},
        "agent_name": "researcher",
        "ttl_seconds": 3600,
        "scope": "tasks:read tasks:write",
    }
