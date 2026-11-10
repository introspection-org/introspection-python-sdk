"""An older SDK reading a newer API through the clients: a response field
this SDK does not model decodes and is kept, at the top level and nested."""

from __future__ import annotations

from typing import Any

import pytest

from introspection_sdk._strict_schema import STRICT_SCHEMA_ENV
from introspection_sdk.resources.annotations import Annotations
from introspection_sdk.runner_resources.tasks import Tasks
from introspection_sdk.schemas.tasks import TaskStatus

from .conftest import ORG_ID, PROJECT_ID, TASK_ID, FakeAPI

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
NOW = "2026-08-25T12:00:00Z"


@pytest.fixture(autouse=True)
def lenient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(STRICT_SCHEMA_ENV, raising=False)


def _annotation(**extra: Any) -> dict[str, Any]:
    return {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "labels": ["needs-review"],
        "assignee_member_ids": [],
        "reviewer_member_ids": [],
        "comment_count": 0,
        "updated_at": NOW,
        "updated_by_member_id": MEMBER_ID,
        **extra,
    }


def test_annotation_page_keeps_unknown_fields(fake_api: FakeAPI):
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

    assert page.model_extra == {"facets": {"labels": 1}}
    [state] = page.records
    assert state.labels == ["needs-review"]
    assert state.model_extra == {"priority": "high", "review": {"score": 3}}


def test_task_keeps_unknown_fields_beside_known_enum_values(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/tasks/{TASK_ID}",
        json_body={
            "id": TASK_ID,
            "org_id": ORG_ID,
            "project_id": PROJECT_ID,
            "created_at": NOW,
            "updated_at": NOW,
            "status": "running",
            "priority": 7,
            "agent": {"session_id": "s-1", "sandbox_region": "eu"},
        },
    )

    task = Tasks(fake_api.client()).get(TASK_ID)

    assert task.status is TaskStatus.RUNNING
    assert task.model_extra == {"priority": 7}
    assert task.agent is not None
    assert task.agent.session_id == "s-1"
    assert task.agent.model_extra == {"sandbox_region": "eu"}
