"""An older SDK reading a newer API: a response field or enum value this
SDK does not know never fails the decode, and an unknown field is ignored
rather than kept as an extra."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from introspection_sdk.resources.annotations import Annotations
from introspection_sdk.resources.experiments import Experiments
from introspection_sdk.runner_resources import Metrics
from introspection_sdk.runner_resources.tasks import Tasks
from introspection_sdk.schemas.experiments import (
    ExperimentStatus,
    JudgeGoalComponent,
    UnknownGoalComponent,
)
from introspection_sdk.schemas.metrics import (
    MetricQueryRequest,
    MetricSpec,
)
from introspection_sdk.schemas.tasks import TaskKind, TaskStatus

from .conftest import (
    EXPERIMENT_ID,
    ORG_ID,
    PROJECT_ID,
    TASK_ID,
    FakeAPI,
)

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
JUDGE_ID = "019fc000-0000-7000-8000-0000000000aa"
NOW = "2026-08-25T12:00:00Z"


def _annotation(**extra: Any) -> dict[str, Any]:
    return {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "labels": ["needs-review"],
        "updated_at": NOW,
        "updated_by_member_id": MEMBER_ID,
        **extra,
    }


def _task(**over: Any) -> dict[str, Any]:
    return {
        "id": TASK_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "status": "running",
        **over,
    }


def test_annotation_page_ignores_unknown_fields(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/annotations",
        json_body={
            "records": [_annotation(priority="high", review={"score": 3})],
            "count": 1,
            "next": None,
            "facets": {"labels": 1},
        },
    )

    page = Annotations(fake_api.client(), fake_api.client()).list().page()

    assert page.model_extra is None
    [state] = page.records
    assert state.trace_id == TRACE_ID
    assert state.labels == ["needs-review"]
    assert state.model_extra is None
    assert "priority" not in state.model_dump()


def test_annotation_navigation_ignores_a_nested_unknown_field(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        "/v1/annotations/navigation",
        json_body={
            "current": _annotation(priority="high"),
            "current_position": 1,
            "total_count": 1,
            "window": 5,
        },
    )

    navigation = Annotations(fake_api.client(), fake_api.client()).navigation(
        trace_id=TRACE_ID, span_id=SPAN_ID
    )

    assert navigation.model_extra is None
    assert navigation.current is not None
    assert navigation.current.span_id == SPAN_ID
    assert navigation.current.model_extra is None


def test_task_with_unknown_fields_and_enum_values_decodes(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        f"/v1/tasks/{TASK_ID}",
        json_body=_task(
            status="hibernating",
            kind="workflow",
            priority=7,
            agent={"session_id": "s-1", "sandbox_region": "eu"},
        ),
    )

    task = Tasks(fake_api.client()).get(TASK_ID)

    assert task.status == "hibernating"
    assert not isinstance(task.status, TaskStatus)
    assert task.kind == "workflow"
    assert task.model_extra is None
    assert "priority" not in task.model_dump()
    assert task.agent is not None
    assert task.agent.session_id == "s-1"
    assert task.agent.model_extra is None


def test_task_list_keeps_known_enum_values_typed(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tasks",
        json_body={
            "records": [
                _task(kind="eval"),
                _task(id=str(UUID(int=1)), status="hibernating"),
            ],
            "count": 2,
            "next": None,
            "cursor_hint": "x",
        },
    )

    known, unknown = Tasks(fake_api.client()).list().records

    assert known.status is TaskStatus.RUNNING
    assert known.kind is TaskKind.EVAL
    assert unknown.status == "hibernating"


def test_experiment_with_an_unknown_goal_component_decodes(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        f"/v1/experiments/{EXPERIMENT_ID}",
        json_body={
            "id": EXPERIMENT_ID,
            "org_id": ORG_ID,
            "project_id": PROJECT_ID,
            "name": "prompt-bake-off",
            "status": "paused",
            "goal_json": {
                "kind": "composite",
                "direction": "maximize",
                "components": [
                    {"source": "judge", "judge_id": JUDGE_ID},
                    {"source": "llm_grader", "weight": 0.5, "model": "m"},
                ],
            },
        },
    )

    experiment = Experiments(fake_api.client()).get(UUID(EXPERIMENT_ID))

    assert experiment.status == "paused"
    assert not isinstance(experiment.status, ExperimentStatus)
    assert experiment.goal_json is not None
    judge, unknown = experiment.goal_json.components
    assert isinstance(judge, JudgeGoalComponent)
    assert judge.judge_id == UUID(JUDGE_ID)
    assert isinstance(unknown, UnknownGoalComponent)
    assert unknown.source == "llm_grader"
    assert unknown.weight == 0.5
    assert unknown.model_extra is None


def test_metrics_response_with_unknown_values_decodes(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/metrics",
        json_body={
            "data": [
                {
                    "metrics": [
                        {
                            "metric_index": 0,
                            "aggregation": "p999",
                            "value": 1.0,
                            "unit": "ms",
                        }
                    ],
                }
            ],
            "meta": {
                "view": "evaluations",
                "window": {"start": NOW, "end": NOW},
                "row_count": 1,
                "row_limit": 100,
                "interval": "1y",
                "order_by": [
                    {
                        "type": "cardinality",
                        "direction": "asc",
                        "nulls": "last",
                    }
                ],
            },
        },
    )

    response = Metrics(fake_api.client()).query(
        MetricQueryRequest(
            view="spans",
            metrics=[MetricSpec(aggregation="count")],
            from_timestamp=datetime(2026, 8, 25, tzinfo=UTC),
            to_timestamp=datetime(2026, 8, 26, tzinfo=UTC),
        )
    )

    assert response.data[0].metrics[0].aggregation == "p999"
    assert response.data[0].metrics[0].model_extra is None
    assert response.meta.view == "evaluations"
    assert response.meta.interval == "1y"
    [order] = response.meta.order_by
    assert order.type == "cardinality"
    assert order.model_extra is None
