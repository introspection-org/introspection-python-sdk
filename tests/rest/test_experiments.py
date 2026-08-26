"""Tests for ``client.experiments``
(:mod:`introspection_sdk.resources.experiments`).
"""

from __future__ import annotations

from uuid import UUID

from introspection_sdk.resources.experiments import Experiments
from introspection_sdk.runner import Runner

from .conftest import (
    EXPERIMENT_ID,
    PROJECT_ID,
    FakeAPI,
    experiment_payload,
    paginated,
    runner_spec_payload,
)

RUNTIME_GROUP_ID = "88888888-8888-8888-8888-888888888888"
TREATMENT_RUNTIME_ID = "99999999-9999-9999-9999-999999999999"
JUDGE_ID = "77777777-7777-7777-7777-777777777777"


def _experiments(fake_api: FakeAPI) -> Experiments:
    return Experiments(fake_api.client())


def test_list(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/experiments", json_body=paginated([experiment_payload()])
    )
    page = _experiments(fake_api).list(
        project=PROJECT_ID, runtime="support-agent", status="running"
    )
    assert page.records[0].name == "prompt-bake-off"
    assert fake_api.last_request.params.get("runtime") == "support-agent"
    assert fake_api.last_request.params.get("status") == "running"


def test_iter_stops_when_no_next(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/experiments", json_body=paginated([experiment_payload()])
    )
    records = list(_experiments(fake_api).list(project=PROJECT_ID))
    assert len(records) == 1


def test_get_without_project_sends_no_params(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(),
    )
    _experiments(fake_api).get(UUID(EXPERIMENT_ID))
    assert list(fake_api.last_request.params.keys()) == []


def test_get_with_project(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(),
    )
    _experiments(fake_api).get(UUID(EXPERIMENT_ID), project=PROJECT_ID)
    assert fake_api.last_request.params.get("project") == PROJECT_ID


def test_create_update_delete_pass_through_documents(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/experiments", json_body=experiment_payload())
    fake_api.add(
        "PATCH",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(name="renamed"),
    )
    fake_api.add("DELETE", f"/v1/experiments/{EXPERIMENT_ID}", status=204)
    experiments = _experiments(fake_api)
    document = {
        "project_id": PROJECT_ID,
        "name": "created",
        "custom": {"kept": True},
    }
    assert experiments.create(document).id == UUID(EXPERIMENT_ID)
    assert fake_api.requests[-1].json() == document
    assert (
        experiments.update(
            UUID(EXPERIMENT_ID), {"name": "renamed"}, project=PROJECT_ID
        ).name
        == "renamed"
    )
    assert fake_api.requests[-1].url.params["project"] == PROJECT_ID
    experiments.delete(UUID(EXPERIMENT_ID), project=PROJECT_ID)
    assert fake_api.requests[-1].method == "DELETE"


def test_handle_run(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/run",
        json_body=runner_spec_payload(),
    )
    runner = _experiments(fake_api)(UUID(EXPERIMENT_ID)).run(
        agent_name="researcher",
        ttl_seconds=60,
        scope="tasks:read",
    )
    assert isinstance(runner, Runner)
    assert fake_api.last_request.json() == {
        "agent_name": "researcher",
        "ttl_seconds": 60,
        "scope": "tasks:read",
    }


def test_handle_lifecycle_start_end_cancel(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/start",
        json_body=experiment_payload(status="running"),
    )
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/end",
        json_body=experiment_payload(status="ended"),
    )
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/cancel",
        json_body=experiment_payload(status="cancelled"),
    )
    handle = _experiments(fake_api)(UUID(EXPERIMENT_ID))

    assert handle.start().status.value == "running"

    ended = handle.end()
    assert ended.status.value == "ended"
    assert fake_api.requests[-1].json() is None

    assert handle.cancel().status.value == "cancelled"


def test_handle_experiment_id_property(fake_api: FakeAPI):
    handle = _experiments(fake_api)(UUID(EXPERIMENT_ID))
    assert handle.experiment_id == UUID(EXPERIMENT_ID)
