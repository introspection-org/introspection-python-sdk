"""Tests for ``client.experiments``
(:mod:`introspection_sdk.resources.experiments`).
"""

from __future__ import annotations

from uuid import UUID

from introspection_sdk.resources.experiments import Experiments
from introspection_sdk.runner import Runner
from introspection_sdk.schemas.experiments import (
    ExperimentArmCreate,
    ExperimentCreate,
    ExperimentGoal,
    JudgeGoalComponent,
)

from .conftest import (
    EXPERIMENT_ID,
    PROJECT_ID,
    RUNTIME_ID,
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
    page = _experiments(fake_api).list(project=PROJECT_ID, status="running")
    assert page.records[0].name == "prompt-bake-off"
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


def test_create_from_model(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/experiments", json_body=experiment_payload())
    _experiments(fake_api).create(
        ExperimentCreate(
            project=PROJECT_ID,
            name="prompt-bake-off",
            runtime_group_id=UUID(RUNTIME_GROUP_ID),
            arms=[
                ExperimentArmCreate(
                    runtime_id=UUID(RUNTIME_ID), arm_label="control"
                ),
                ExperimentArmCreate(
                    runtime_id=UUID(TREATMENT_RUNTIME_ID),
                    arm_label="treatment",
                ),
            ],
            goal_json=ExperimentGoal(
                components=[JudgeGoalComponent(judge_id=UUID(JUDGE_ID))]
            ),
        )
    )
    body = fake_api.last_request.json()
    assert body["name"] == "prompt-bake-off"
    assert body["runtime_group_id"] == RUNTIME_GROUP_ID
    assert [arm["arm_label"] for arm in body["arms"]] == [
        "control",
        "treatment",
    ]
    goal_component = body["goal_json"]["components"][0]
    assert goal_component["source"] == "judge"
    assert goal_component["judge_id"] == JUDGE_ID


def test_create_from_dict(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/experiments", json_body=experiment_payload())
    _experiments(fake_api).create(
        {"project": PROJECT_ID, "name": "x", "description": None}
    )
    assert "description" not in fake_api.last_request.json()


def test_update(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body=experiment_payload(name="renamed"),
    )
    exp = _experiments(fake_api).update(
        UUID(EXPERIMENT_ID), {"name": "renamed"}
    )
    assert exp.name == "renamed"


def test_delete_expects_empty(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/experiments/{EXPERIMENT_ID}", status=204)
    assert _experiments(fake_api).delete(UUID(EXPERIMENT_ID)) is None


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
