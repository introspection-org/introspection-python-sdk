"""Tests for ``client.experiments``
(:mod:`introspection_sdk.resources.experiments`).
"""

from __future__ import annotations

from uuid import UUID

from introspection_sdk.resources.experiments import Experiments
from introspection_sdk.runner import Runner
from introspection_sdk.schemas.experiments import ExperimentCreate

from .conftest import (
    EXPERIMENT_ID,
    PROJECT_ID,
    FakeAPI,
    experiment_payload,
    paginated,
    runner_spec_payload,
)


def _experiments(fake_api: FakeAPI) -> Experiments:
    return Experiments(fake_api.client())


def test_list(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/experiments", json_body=paginated([experiment_payload()])
    )
    page = _experiments(fake_api).list(project_id=PROJECT_ID, status="running")
    assert page.records[0].name == "prompt-bake-off"
    assert fake_api.last_request.params.get("status") == "running"


def test_iter_stops_when_no_next(fake_api: FakeAPI):
    fake_api.add(
        "GET", "/v1/experiments", json_body=paginated([experiment_payload()])
    )
    records = list(_experiments(fake_api).iter(project_id=PROJECT_ID))
    assert len(records) == 1


def test_get_without_project_id_sends_no_params(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(),
    )
    _experiments(fake_api).get(EXPERIMENT_ID)
    assert list(fake_api.last_request.params.keys()) == []


def test_get_with_project_id(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(),
    )
    _experiments(fake_api).get(EXPERIMENT_ID, project_id=PROJECT_ID)
    assert fake_api.last_request.params.get("project_id") == PROJECT_ID


def test_create_from_model(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/experiments", json_body=experiment_payload())
    _experiments(fake_api).create(
        ExperimentCreate(project_id=UUID(PROJECT_ID), name="prompt-bake-off")
    )
    assert fake_api.last_request.json()["name"] == "prompt-bake-off"


def test_create_from_dict(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/experiments", json_body=experiment_payload())
    _experiments(fake_api).create(
        {"project_id": PROJECT_ID, "name": "x", "description": None}
    )
    assert "description" not in fake_api.last_request.json()


def test_update(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(name="renamed"),
    )
    exp = _experiments(fake_api).update(EXPERIMENT_ID, {"name": "renamed"})
    assert exp.name == "renamed"


def test_delete_expects_empty(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/experiments/{EXPERIMENT_ID}", status=204)
    assert _experiments(fake_api).delete(EXPERIMENT_ID) is None


def test_handle_run(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/run",
        json_body=runner_spec_payload(),
    )
    runner = _experiments(fake_api)(EXPERIMENT_ID).run(ttl_seconds=60)
    assert isinstance(runner, Runner)
    assert fake_api.last_request.json()["ttl_seconds"] == 60


def test_handle_lifecycle_start_end_cancel(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/start",
        json_body=experiment_payload(status="running"),
    )
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/end",
        json_body=experiment_payload(status="concluded"),
    )
    fake_api.add(
        "POST",
        f"/v1/experiments/{EXPERIMENT_ID}/cancel",
        json_body=experiment_payload(status="cancelled"),
    )
    handle = _experiments(fake_api)(EXPERIMENT_ID)

    assert handle.start().status.value == "running"

    ended = handle.end(winning_arm_label="treatment", notes="ship it")
    assert ended.status.value == "concluded"
    end_body = fake_api.requests[-1].json()
    assert end_body == {"winning_arm_label": "treatment", "notes": "ship it"}

    assert handle.cancel().status.value == "cancelled"


def test_handle_experiment_id_property(fake_api: FakeAPI):
    handle = _experiments(fake_api)(EXPERIMENT_ID)
    assert handle.experiment_id == EXPERIMENT_ID
