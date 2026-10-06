"""Contract tests for ``client.automations`` and the automation event families.

Driven through the offline :class:`FakeAPI` transport from ``conftest.py`` —
nothing in ``introspection_sdk`` is patched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2 as httpx
import pydantic
import pytest

from introspection_sdk import AsyncIntrospectionClient, IntrospectionClient
from introspection_sdk._errors import ConflictError, IntrospectionAPIError
from introspection_sdk.runner_resources.automations import (
    AsyncAutomations,
    Automations,
)
from introspection_sdk.runner_resources.events import AsyncEvents, Events
from introspection_sdk.schemas.automations import (
    AutomationConditionType,
    AutomationExecutionStatus,
    AutomationKind,
    AutomationMetadata,
    AutomationSkipReason,
    AutomationTriggerType,
)
from introspection_sdk.schemas.events import (
    AutomationSkippedEvent,
    AutomationTriggeredEvent,
    IntrospectionEventName,
)
from introspection_sdk.schemas.tasks import TaskRepoRequest

from .conftest import (
    MEMBER_ID,
    ORG_ID,
    PROJECT_ID,
    RUNTIME_GROUP_ID,
    TASK_ID,
    FakeAPI,
)

AUTOMATION_ID = "0199a1b2-0000-7000-8000-000000000001"
AUTOMATION_PATH = f"/v1/automations/{AUTOMATION_ID}"


def automation_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": AUTOMATION_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "name": "Weekly digest",
        "description": "Summarize the week",
        "enabled": True,
        "runtime_group_id": RUNTIME_GROUP_ID,
        "task_id": TASK_ID,
        "created_by_member_id": MEMBER_ID,
        "execution_blocked_reason": None,
        "can_manage": True,
        "tags": ["digest"],
        "trigger_type": "cron",
        "cron_schedule": "0 9 * * 1",
        "kind": None,
        "prompt": "Summarize my week",
        "metadata": {
            "cron_schedules": ["0 9 * * 1", "0 17 * * 5"],
            "timezone": "Europe/London",
            "repositories": [{"repo": "acme/app", "ref": "main"}],
            "conditions": [
                {"type": "has_new_tasks_since_last_run"},
                {"type": "brand_new_condition"},
            ],
        },
        "last_triggered_at": "2026-09-28T09:00:00Z",
        "next_trigger_at": "2026-10-05T09:00:00.123456Z",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-28T09:00:01Z",
        "owner_role": "operator",
        # Still on the wire until introspection-cloud#3154 drops it.
        "agent_member_id": None,
    }
    body.update(over)
    return body


def page(records: list[dict[str, Any]], next: str | None = None) -> dict:
    return {"records": records, "count": len(records), "next": next}


def paged_handler(pages: list[dict[str, Any]]):
    """Serve ``pages`` in order, one per request."""
    remaining = list(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remaining.pop(0))

    return handler


def test_client_exposes_automations_on_the_data_plane(fake_api: FakeAPI):
    client = IntrospectionClient(
        token="t",
        base_api_url="https://api.test",
        dp_url="https://dp.test",
    )
    try:
        assert isinstance(client.automations, Automations)
        assert client.automations._http is client._dp_http
    finally:
        client.shutdown()


async def test_async_client_exposes_automations():
    client = AsyncIntrospectionClient(
        token="t", base_api_url="https://api.test"
    )
    try:
        assert isinstance(client.automations, AsyncAutomations)
    finally:
        await client.shutdown()


def test_get_decodes_the_server_automation(fake_api: FakeAPI):
    fake_api.add("GET", AUTOMATION_PATH, json_body=automation_body())

    automation = Automations(fake_api.client()).get(UUID(AUTOMATION_ID))

    assert fake_api.last_request.method == "GET"
    assert automation.name == "Weekly digest"
    assert automation.trigger_type is AutomationTriggerType.CRON
    assert automation.kind is None
    assert automation.can_manage is True
    assert automation.runtime_group_id == UUID(RUNTIME_GROUP_ID)
    assert automation.task_id == UUID(TASK_ID)
    assert automation.created_by_member_id == UUID(MEMBER_ID)
    assert automation.owner_role == "operator"
    assert automation.tags == ["digest"]
    assert automation.last_triggered_at == datetime(2026, 9, 28, 9, tzinfo=UTC)
    assert automation.next_trigger_at == datetime(
        2026, 10, 5, 9, 0, 0, 123456, tzinfo=UTC
    )

    metadata = automation.typed_metadata
    assert metadata is not None
    assert metadata.cron_schedules == ["0 9 * * 1", "0 17 * * 5"]
    assert metadata.timezone == "Europe/London"
    assert metadata.repositories == [
        TaskRepoRequest(repo="acme/app", ref="main")
    ]
    assert metadata.conditions is not None
    types = [condition.type for condition in metadata.conditions]
    assert types == ["has_new_tasks_since_last_run", "brand_new_condition"]
    assert types[0] is AutomationConditionType.HAS_NEW_TASKS_SINCE_LAST_RUN
    assert not isinstance(types[1], AutomationConditionType)


def test_minimal_automation_and_unfit_metadata(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/automations/a",
        json_body={
            "id": AUTOMATION_ID,
            "name": "n",
            "trigger_type": "manual",
            "kind": "observation_clustering",
        },
    )
    fake_api.add(
        "GET",
        "/v1/automations/b",
        json_body=automation_body(metadata={"cron_schedules": "not-a-list"}),
    )
    api = Automations(fake_api.client())

    minimal = api.get("a")
    assert minimal.kind is AutomationKind.OBSERVATION_CLUSTERING
    assert minimal.metadata is None
    assert minimal.typed_metadata is None
    assert minimal.runtime_group_id is None
    assert minimal.task_id is None
    assert minimal.next_trigger_at is None
    assert minimal.tags == []

    assert api.get("b").typed_metadata is None


def test_list_encodes_filters_and_paginates(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/automations",
        paged_handler(
            [
                page([automation_body()], next="cur-2"),
                page(
                    [
                        {
                            "id": AUTOMATION_ID,
                            "name": "second",
                            "trigger_type": "manual",
                        }
                    ]
                ),
            ]
        ),
    )

    names = [
        a.name
        for a in Automations(fake_api.client()).list(
            kind=AutomationKind.OBSERVATION_SYNTHESIS,
            enabled=True,
            scheduled=False,
            limit=1,
        )
    ]

    assert names == ["Weekly digest", "second"]
    assert len(fake_api.requests) == 2
    first = fake_api.requests[0]
    assert first.path == "/v1/automations"
    assert dict(first.params) == {
        "limit": "1",
        "kind": "observation_synthesis",
        "enabled": "true",
        "scheduled": "false",
    }
    assert fake_api.requests[1].params["next"] == "cur-2"


def test_list_keeps_task_id_on_every_page(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/automations",
        paged_handler(
            [
                page([automation_body()], next="cur-2"),
                page([automation_body(name="second")]),
            ]
        ),
    )

    automations = list(
        Automations(fake_api.client()).list(task_id=UUID(TASK_ID))
    )

    assert [a.name for a in automations] == ["Weekly digest", "second"]
    assert [dict(r.params) for r in fake_api.requests] == [
        {"task_id": TASK_ID},
        {"task_id": TASK_ID, "next": "cur-2"},
    ]


def test_list_starts_from_a_cursor_and_omits_unset_filters(
    fake_api: FakeAPI,
):
    fake_api.add("GET", "/v1/automations", json_body=page([]))

    Automations(fake_api.client()).list(next="cur-9").page()

    assert dict(fake_api.last_request.params) == {"next": "cur-9"}


def test_list_decodes_the_check_in_and_an_unknown_kind(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/automations",
        json_body=page(
            [
                automation_body(
                    kind="project_check_in",
                    task_id=None,
                    owner_role="operator",
                ),
                automation_body(
                    kind="not_yet_invented",
                    trigger_type="on_webhook",
                    owner_role=None,
                ),
            ]
        ),
    )

    check_in, later = Automations(fake_api.client()).list().page().records

    assert check_in.kind is AutomationKind.PROJECT_CHECK_IN
    assert check_in.owner_role == "operator"
    assert later.kind == "not_yet_invented"
    assert not isinstance(later.kind, AutomationKind)
    assert later.trigger_type == "on_webhook"
    assert later.owner_role is None


def test_list_surfaces_the_admin_only_403(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/automations",
        status=403,
        json_body={"detail": "Only administrators can access automations"},
    )

    with pytest.raises(IntrospectionAPIError) as exc:
        Automations(fake_api.client()).list().page()
    assert exc.value.status_code == 403


def test_create_sends_only_set_fields(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/automations", status=201, json_body=automation_body()
    )
    api = Automations(fake_api.client())

    created = api.create(
        name="Weekly digest",
        trigger_type=AutomationTriggerType.CRON,
        cron_schedule="0 9 * * 1",
        prompt="Summarize my week",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        metadata=AutomationMetadata(
            cron_schedules=["0 9 * * 1"], timezone="UTC"
        ),
    )

    assert created.name == "Weekly digest"
    assert fake_api.last_request.method == "POST"
    assert fake_api.last_request.path == "/v1/automations"
    assert fake_api.last_request.json() == {
        "name": "Weekly digest",
        "trigger_type": "cron",
        "cron_schedule": "0 9 * * 1",
        "prompt": "Summarize my week",
        "runtime_group_id": RUNTIME_GROUP_ID,
        "metadata": {"cron_schedules": ["0 9 * * 1"], "timezone": "UTC"},
    }

    api.create(
        name="Clusters",
        trigger_type="manual",
        kind=AutomationKind.OBSERVATION_CLUSTERING,
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        metadata={"conditions": [{"type": "has_new_tasks_since_last_run"}]},
        enabled=False,
    )
    assert fake_api.last_request.json() == {
        "name": "Clusters",
        "trigger_type": "manual",
        "kind": "observation_clustering",
        "runtime_group_id": RUNTIME_GROUP_ID,
        "metadata": {"conditions": [{"type": "has_new_tasks_since_last_run"}]},
        "enabled": False,
    }


def test_create_a_one_off_reminder_into_an_existing_task(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/automations", status=201, json_body=automation_body()
    )

    Automations(fake_api.client()).create(
        name="Friday check-in",
        trigger_type=AutomationTriggerType.MANUAL,
        prompt="How did the week go?",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        task_id=UUID(TASK_ID),
        next_trigger_at=datetime(2026, 10, 10, 9, tzinfo=UTC),
        description="Ask on Friday",
    )

    assert fake_api.last_request.json() == {
        "name": "Friday check-in",
        "trigger_type": "manual",
        "description": "Ask on Friday",
        "prompt": "How did the week go?",
        "runtime_group_id": RUNTIME_GROUP_ID,
        "task_id": TASK_ID,
        "next_trigger_at": "2026-10-10T09:00:00Z",
    }


@pytest.mark.parametrize(
    ("kwargs", "body"),
    [
        ({"enabled": False}, {"enabled": False}),
        (
            {"next_trigger_at": datetime(2026, 10, 12, 8, 30, tzinfo=UTC)},
            {"next_trigger_at": "2026-10-12T08:30:00Z"},
        ),
        (
            {
                "runtime_group_id": UUID(RUNTIME_GROUP_ID),
                "task_id": UUID(TASK_ID),
            },
            {"runtime_group_id": RUNTIME_GROUP_ID, "task_id": TASK_ID},
        ),
        (
            {
                "name": "n",
                "description": "d",
                "cron_schedule": "0 * * * *",
                "prompt": "p",
                "metadata": AutomationMetadata(timezone="Asia/Tokyo"),
            },
            {
                "name": "n",
                "description": "d",
                "cron_schedule": "0 * * * *",
                "prompt": "p",
                "metadata": {"timezone": "Asia/Tokyo"},
            },
        ),
        # An empty map is sent: metadata replaces wholesale.
        ({"metadata": {}}, {"metadata": {}}),
        ({}, {}),
    ],
)
def test_update_sends_only_set_fields(
    fake_api: FakeAPI, kwargs: dict[str, Any], body: dict[str, Any]
):
    fake_api.add("PATCH", AUTOMATION_PATH, json_body=automation_body())

    Automations(fake_api.client()).update(UUID(AUTOMATION_ID), **kwargs)

    assert fake_api.last_request.method == "PATCH"
    assert fake_api.last_request.json() == body


def test_delete_and_trigger_escape_the_id(fake_api: FakeAPI):
    # FakeAPI routes on the decoded path; the raw path is asserted below.
    fake_api.add("DELETE", "/v1/automations/a/1", status=204)
    fake_api.add(
        "POST",
        "/v1/automations/a/1/trigger",
        status=202,
        json_body={
            "status": "triggered",
            "automation_id": AUTOMATION_ID,
            "task_id": TASK_ID,
            "reason": None,
        },
    )
    api = Automations(fake_api.client())

    assert api.delete("a/1") is None
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.url.raw_path == b"/v1/automations/a%2F1"

    triggered = api.trigger("a/1")
    assert fake_api.last_request.method == "POST"
    assert (
        fake_api.last_request.url.raw_path == b"/v1/automations/a%2F1/trigger"
    )
    assert triggered.status is AutomationExecutionStatus.TRIGGERED
    assert triggered.task_id == UUID(TASK_ID)
    assert triggered.automation_id == UUID(AUTOMATION_ID)
    assert triggered.reason is None


def test_delete_of_a_project_default_is_a_conflict(fake_api: FakeAPI):
    fake_api.add(
        "DELETE",
        AUTOMATION_PATH,
        status=409,
        json_body={"detail": "A default automation cannot be deleted."},
    )

    with pytest.raises(ConflictError):
        Automations(fake_api.client()).delete(UUID(AUTOMATION_ID))


def test_hand_trigger_skip_carries_its_reason(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"{AUTOMATION_PATH}/trigger",
        status=202,
        json_body={
            "status": "skipped",
            "automation_id": AUTOMATION_ID,
            "task_id": None,
            "reason": "Target task is archived",
        },
    )

    skipped = Automations(fake_api.client()).trigger(AUTOMATION_ID)

    assert skipped.status is AutomationExecutionStatus.SKIPPED
    assert skipped.task_id is None
    assert skipped.reason == "Target task is archived"


async def test_async_crud_and_trigger(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/automations",
        paged_handler(
            [
                page([automation_body()], next="cur-2"),
                page([automation_body(name="second")]),
            ]
        ),
    )
    fake_api.add("GET", AUTOMATION_PATH, json_body=automation_body())
    fake_api.add(
        "POST", "/v1/automations", status=201, json_body=automation_body()
    )
    fake_api.add("PATCH", AUTOMATION_PATH, json_body=automation_body())
    fake_api.add("DELETE", AUTOMATION_PATH, status=204)
    fake_api.add(
        "POST",
        f"{AUTOMATION_PATH}/trigger",
        status=202,
        json_body={"status": "cancelled", "automation_id": AUTOMATION_ID},
    )
    api = AsyncAutomations(fake_api.async_client())

    names = [a.name async for a in api.list(task_id=TASK_ID, enabled=True)]
    assert names == ["Weekly digest", "second"]
    assert [dict(r.params) for r in fake_api.requests] == [
        {"enabled": "true", "task_id": TASK_ID},
        {"enabled": "true", "task_id": TASK_ID, "next": "cur-2"},
    ]

    assert (await api.get(AUTOMATION_ID)).name == "Weekly digest"

    await api.create(
        name="n",
        trigger_type="manual",
        prompt="p",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        task_id=UUID(TASK_ID),
    )
    assert fake_api.last_request.json() == {
        "name": "n",
        "trigger_type": "manual",
        "prompt": "p",
        "runtime_group_id": RUNTIME_GROUP_ID,
        "task_id": TASK_ID,
    }

    await api.update(AUTOMATION_ID, prompt="new")
    assert fake_api.last_request.json() == {"prompt": "new"}

    await api.delete(AUTOMATION_ID)
    assert fake_api.last_request.method == "DELETE"

    result = await api.trigger(AUTOMATION_ID)
    assert result.status is AutomationExecutionStatus.CANCELLED


# --- automation events ----------------------------------------------------

TRIGGERED_ROW: dict[str, Any] = {
    "id": "0199a1b2-0000-5000-8000-000000000001",
    "timestamp": "2026-10-05T09:00:02Z",
    "event_name": "introspection.automation.triggered",
    "conversation_id": "conv-1",
    "runtime_group_id": RUNTIME_GROUP_ID,
    "payload": {
        "automation_id": AUTOMATION_ID,
        "automation_name": "Weekly digest",
        "prompt": "Summarize my week",
        "trigger_type": "cron",
        "slot": "2026-10-05T09:00:00Z",
        "task_id": TASK_ID,
        "posted": True,
        "member_id": MEMBER_ID,
        "runtime_group_id": RUNTIME_GROUP_ID,
        "triggered_by_member_id": None,
    },
}

SKIPPED_ROW: dict[str, Any] = {
    "id": "0199a1b2-0000-5000-8000-000000000002",
    "timestamp": "2026-10-06T09:00:00Z",
    "event_name": "introspection.automation.skipped",
    "runtime_group_id": RUNTIME_GROUP_ID,
    "payload": {
        "automation_id": AUTOMATION_ID,
        "trigger_type": "manual",
        "slot": "2026-10-06T09:00:00Z",
        "task_id": TASK_ID,
        "reason": "target_busy",
    },
}


def test_events_read_triggered_rows_with_automation_filters(
    fake_api: FakeAPI,
):
    fake_api.add("GET", "/v1/events", json_body=page([TRIGGERED_ROW]))

    events = list(
        Events(fake_api.client()).list(
            IntrospectionEventName.AUTOMATION_TRIGGERED,
            automation_id=UUID(AUTOMATION_ID),
            task_id=TASK_ID,
        )
    )

    params = fake_api.last_request.params
    assert params["event_name"] == "introspection.automation.triggered"
    assert params["automation_id"] == AUTOMATION_ID
    assert params["task_id"] == TASK_ID

    (event,) = events
    assert isinstance(event, AutomationTriggeredEvent)
    run = event.payload
    assert run.automation_name == "Weekly digest"
    assert run.trigger_type is AutomationTriggerType.CRON
    assert run.slot == datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert run.posted is True
    assert run.task_id == UUID(TASK_ID)
    assert run.member_id == UUID(MEMBER_ID)
    assert run.triggered_by_member_id is None
    assert event.conversation_id == "conv-1"


def test_events_read_skipped_rows_including_an_unknown_reason(
    fake_api: FakeAPI,
):
    unknown = {
        **SKIPPED_ROW,
        "id": "0199a1b2-0000-5000-8000-000000000003",
        "payload": {
            **SKIPPED_ROW["payload"],
            "task_id": None,
            "reason": "reason_from_the_future",
        },
    }
    fake_api.add("GET", "/v1/events", json_body=page([SKIPPED_ROW, unknown]))

    known, future = (
        Events(fake_api.client())
        .list("introspection.automation.skipped")
        .page()
        .records
    )

    assert isinstance(known, AutomationSkippedEvent)
    assert known.payload.reason is AutomationSkipReason.TARGET_BUSY
    assert known.payload.trigger_type is AutomationTriggerType.MANUAL
    assert known.payload.task_id == UUID(TASK_ID)
    assert isinstance(future, AutomationSkippedEvent)
    assert future.payload.reason == "reason_from_the_future"
    assert future.payload.task_id is None


def test_event_get_resolves_an_automation_family(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/events/{SKIPPED_ROW['id']}", json_body=SKIPPED_ROW
    )

    event = Events(fake_api.client()).get(SKIPPED_ROW["id"])

    assert isinstance(event, AutomationSkippedEvent)


async def test_async_events_send_automation_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/events", json_body=page([TRIGGERED_ROW]))

    records = await AsyncEvents(fake_api.async_client()).list(
        IntrospectionEventName.AUTOMATION_TRIGGERED,
        automation_id=AUTOMATION_ID,
        task_id=UUID(TASK_ID),
    )

    assert isinstance(records.records[0], AutomationTriggeredEvent)
    params = fake_api.last_request.params
    assert params["automation_id"] == AUTOMATION_ID
    assert params["task_id"] == TASK_ID


def test_create_rejects_a_naive_slot_before_sending(fake_api: FakeAPI):
    with pytest.raises(pydantic.ValidationError):
        Automations(fake_api.client()).create(
            name="One-off",
            trigger_type="manual",
            prompt="Go",
            runtime_group_id=UUID(RUNTIME_GROUP_ID),
            next_trigger_at=datetime(2026, 2, 1, 9, 0),
        )
    with pytest.raises(pydantic.ValidationError):
        Automations(fake_api.client()).update(
            AUTOMATION_ID, next_trigger_at=datetime(2026, 2, 1, 9, 0)
        )
    assert fake_api.requests == []


def test_get_decodes_soft_delete_agent_and_operator_default(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        AUTOMATION_PATH,
        json_body=automation_body(
            deleted_at="2026-10-01T09:00:00Z",
            agent_member_id=MEMBER_ID,
            metadata={"operator_default": "project_check_in"},
        ),
    )

    automation = Automations(fake_api.client()).get(AUTOMATION_ID)

    assert automation.deleted_at == datetime(2026, 10, 1, 9, tzinfo=UTC)
    assert automation.agent_member_id == UUID(MEMBER_ID)
    metadata = automation.typed_metadata
    assert metadata is not None
    assert metadata.operator_default == "project_check_in"
