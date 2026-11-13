"""Contract tests for ``client.routines`` and the routine event families.

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
from introspection_sdk.runner_resources.events import AsyncEvents, Events
from introspection_sdk.runner_resources.routines import (
    AsyncRoutines,
    Routines,
)
from introspection_sdk.schemas.events import (
    IntrospectionEventName,
    RoutineSkippedEvent,
    RoutineTriggeredEvent,
)
from introspection_sdk.schemas.routines import (
    EnqueuedConversation,
    RoutineConditionType,
    RoutineExecutionStatus,
    RoutineKind,
    RoutineMetadata,
    RoutineRunSource,
    RoutineSkipReason,
    RoutineTriggerFilter,
    RoutineTriggerProvider,
    RoutineTriggerSource,
    RoutineTriggerSpec,
    RoutineTriggerType,
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

ROUTINE_ID = "0199a1b2-0000-7000-8000-000000000001"
ROUTINE_PATH = f"/v1/routines/{ROUTINE_ID}"


def routine_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": ROUTINE_ID,
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


def test_client_exposes_routines_on_the_data_plane(fake_api: FakeAPI):
    client = IntrospectionClient(
        token="t",
        base_api_url="https://api.test",
        dp_url="https://dp.test",
    )
    try:
        assert isinstance(client.routines, Routines)
        assert client.routines._http is client._dp_http
    finally:
        client.shutdown()


async def test_async_client_exposes_routines():
    client = AsyncIntrospectionClient(
        token="t", base_api_url="https://api.test"
    )
    try:
        assert isinstance(client.routines, AsyncRoutines)
    finally:
        await client.shutdown()


def test_get_decodes_the_server_routine(fake_api: FakeAPI):
    fake_api.add("GET", ROUTINE_PATH, json_body=routine_body())

    routine = Routines(fake_api.client()).get(UUID(ROUTINE_ID))

    assert fake_api.last_request.method == "GET"
    assert routine.name == "Weekly digest"
    assert routine.trigger_type is RoutineTriggerType.CRON
    assert routine.kind is None
    assert routine.can_manage is True
    assert routine.runtime_group_id == UUID(RUNTIME_GROUP_ID)
    assert routine.task_id == UUID(TASK_ID)
    assert routine.created_by_member_id == UUID(MEMBER_ID)
    assert routine.owner_role == "operator"
    assert routine.tags == ["digest"]
    assert routine.last_triggered_at == datetime(2026, 9, 28, 9, tzinfo=UTC)
    assert routine.next_trigger_at == datetime(
        2026, 10, 5, 9, 0, 0, 123456, tzinfo=UTC
    )

    metadata = routine.typed_metadata
    assert metadata is not None
    assert metadata.cron_schedules == ["0 9 * * 1", "0 17 * * 5"]
    assert metadata.timezone == "Europe/London"
    assert metadata.repositories == [
        TaskRepoRequest(repo="acme/app", ref="main")
    ]
    assert metadata.conditions is not None
    types = [condition.type for condition in metadata.conditions]
    assert types == ["has_new_tasks_since_last_run", "brand_new_condition"]
    assert types[0] is RoutineConditionType.HAS_NEW_TASKS_SINCE_LAST_RUN
    assert not isinstance(types[1], RoutineConditionType)


def test_minimal_routine_and_unfit_metadata(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/routines/a",
        json_body={
            "id": ROUTINE_ID,
            "name": "n",
            "trigger_type": "manual",
            "kind": "observation_clustering",
        },
    )
    fake_api.add(
        "GET",
        "/v1/routines/b",
        json_body=routine_body(metadata={"cron_schedules": "not-a-list"}),
    )
    api = Routines(fake_api.client())

    minimal = api.get("a")
    assert minimal.kind is RoutineKind.OBSERVATION_CLUSTERING
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
        "/v1/routines",
        paged_handler(
            [
                page([routine_body()], next="cur-2"),
                page(
                    [
                        {
                            "id": ROUTINE_ID,
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
        for a in Routines(fake_api.client()).list(
            kind=RoutineKind.OBSERVATION_SYNTHESIS,
            enabled=True,
            scheduled=False,
            limit=1,
        )
    ]

    assert names == ["Weekly digest", "second"]
    assert len(fake_api.requests) == 2
    first = fake_api.requests[0]
    assert first.path == "/v1/routines"
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
        "/v1/routines",
        paged_handler(
            [
                page([routine_body()], next="cur-2"),
                page([routine_body(name="second")]),
            ]
        ),
    )

    routines = list(Routines(fake_api.client()).list(task_id=UUID(TASK_ID)))

    assert [a.name for a in routines] == ["Weekly digest", "second"]
    assert [dict(r.params) for r in fake_api.requests] == [
        {"task_id": TASK_ID},
        {"task_id": TASK_ID, "next": "cur-2"},
    ]


def test_list_starts_from_a_cursor_and_omits_unset_filters(
    fake_api: FakeAPI,
):
    fake_api.add("GET", "/v1/routines", json_body=page([]))

    Routines(fake_api.client()).list(next="cur-9").page()

    assert dict(fake_api.last_request.params) == {"next": "cur-9"}


def test_list_decodes_the_check_in_and_an_unknown_kind(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/routines",
        json_body=page(
            [
                routine_body(
                    kind="project_check_in",
                    task_id=None,
                    owner_role="operator",
                ),
                routine_body(
                    kind="not_yet_invented",
                    trigger_type="on_webhook",
                    owner_role=None,
                ),
            ]
        ),
    )

    check_in, later = Routines(fake_api.client()).list().page().records

    assert check_in.kind is RoutineKind.PROJECT_CHECK_IN
    assert check_in.owner_role == "operator"
    assert later.kind == "not_yet_invented"
    assert not isinstance(later.kind, RoutineKind)
    assert later.trigger_type == "on_webhook"
    assert later.owner_role is None


def test_list_surfaces_the_admin_only_403(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/routines",
        status=403,
        json_body={"detail": "Only administrators can access routines"},
    )

    with pytest.raises(IntrospectionAPIError) as exc:
        Routines(fake_api.client()).list().page()
    assert exc.value.status_code == 403


def test_create_sends_only_set_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/routines", status=201, json_body=routine_body())
    api = Routines(fake_api.client())

    created = api.create(
        name="Weekly digest",
        trigger_type=RoutineTriggerType.CRON,
        cron_schedule="0 9 * * 1",
        prompt="Summarize my week",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        metadata=RoutineMetadata(cron_schedules=["0 9 * * 1"], timezone="UTC"),
    )

    assert created.name == "Weekly digest"
    assert fake_api.last_request.method == "POST"
    assert fake_api.last_request.path == "/v1/routines"
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
        kind=RoutineKind.OBSERVATION_CLUSTERING,
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
    fake_api.add("POST", "/v1/routines", status=201, json_body=routine_body())

    Routines(fake_api.client()).create(
        name="Friday check-in",
        trigger_type=RoutineTriggerType.MANUAL,
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
                "metadata": RoutineMetadata(timezone="Asia/Tokyo"),
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
    fake_api.add("PATCH", ROUTINE_PATH, json_body=routine_body())

    Routines(fake_api.client()).update(UUID(ROUTINE_ID), **kwargs)

    assert fake_api.last_request.method == "PATCH"
    assert fake_api.last_request.json() == body


def test_delete_and_trigger_escape_the_id(fake_api: FakeAPI):
    # FakeAPI routes on the decoded path; the raw path is asserted below.
    fake_api.add("DELETE", "/v1/routines/a/1", status=204)
    fake_api.add(
        "POST",
        "/v1/routines/a/1/trigger",
        status=202,
        json_body={
            "status": "triggered",
            "routine_id": ROUTINE_ID,
            "task_id": TASK_ID,
            "reason": None,
        },
    )
    api = Routines(fake_api.client())

    assert api.delete("a/1") is None
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.url.raw_path == b"/v1/routines/a%2F1"

    triggered = api.trigger("a/1")
    assert fake_api.last_request.method == "POST"
    assert fake_api.last_request.url.raw_path == b"/v1/routines/a%2F1/trigger"
    assert triggered.status is RoutineExecutionStatus.TRIGGERED
    assert triggered.task_id == UUID(TASK_ID)
    assert triggered.routine_id == UUID(ROUTINE_ID)
    assert triggered.reason is None


def test_delete_of_a_project_default_is_a_conflict(fake_api: FakeAPI):
    fake_api.add(
        "DELETE",
        ROUTINE_PATH,
        status=409,
        json_body={"detail": "A default routine cannot be deleted."},
    )

    with pytest.raises(ConflictError):
        Routines(fake_api.client()).delete(UUID(ROUTINE_ID))


def test_hand_trigger_skip_carries_its_reason(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"{ROUTINE_PATH}/trigger",
        status=202,
        json_body={
            "status": "skipped",
            "routine_id": ROUTINE_ID,
            "task_id": None,
            "reason": "Target task is archived",
        },
    )

    skipped = Routines(fake_api.client()).trigger(ROUTINE_ID)

    assert skipped.status is RoutineExecutionStatus.SKIPPED
    assert skipped.task_id is None
    assert skipped.reason == "Target task is archived"


def test_hand_trigger_reports_what_synthesis_queued(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"{ROUTINE_PATH}/trigger",
        status=202,
        json_body={
            "status": "triggered",
            "routine_id": ROUTINE_ID,
            "task_id": None,
            "run_id": None,
            "reason": None,
            "result": {
                "enqueued": 1,
                "conversations": [
                    {
                        "conversation_id": "conv-1",
                        "completed_at": "2026-11-12T09:00:00Z",
                    }
                ],
            },
        },
    )

    queued = Routines(fake_api.client()).trigger(
        ROUTINE_ID, parameters={"conversation_ids": ["conv-1"]}
    )

    assert fake_api.last_request.json() == {
        "parameters": {"conversation_ids": ["conv-1"]}
    }
    assert queued.status is RoutineExecutionStatus.TRIGGERED
    assert queued.run_id is None
    assert queued.result is not None
    assert queued.result["enqueued"] == 1
    (conversation,) = [
        EnqueuedConversation.model_validate(c)
        for c in queued.result["conversations"]
    ]
    assert conversation.conversation_id == "conv-1"
    assert conversation.completed_at == datetime(2026, 11, 12, 9, tzinfo=UTC)
    assert not hasattr(queued, "enqueued")


def test_hand_trigger_sends_parameters_and_nothing_else(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"{ROUTINE_PATH}/trigger",
        status=202,
        json_body={
            "status": "triggered",
            "routine_id": ROUTINE_ID,
            "task_id": TASK_ID,
            "run_id": None,
            "reason": None,
            "result": None,
        },
    )
    api = Routines(fake_api.client())

    parameters = {"order_id": "o-1", "lines": [{"sku": "a", "qty": 2}]}
    triggered = api.trigger(ROUTINE_ID, parameters=parameters)
    assert fake_api.last_request.json() == {"parameters": parameters}
    assert triggered.task_id == UUID(TASK_ID)
    assert triggered.result is None

    # An empty object is a run with parameters, not a run without.
    api.trigger(ROUTINE_ID, parameters={})
    assert fake_api.last_request.json() == {"parameters": {}}

    api.trigger(ROUTINE_ID)
    assert fake_api.last_request.content == b""


def test_hand_trigger_surfaces_oversized_parameters_422(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"{ROUTINE_PATH}/trigger",
        status=422,
        json_body={
            "detail": [
                {
                    "type": "value_error",
                    "loc": ["body", "parameters"],
                    "msg": "parameters nest at most 8 levels deep",
                }
            ]
        },
    )

    with pytest.raises(IntrospectionAPIError) as exc:
        Routines(fake_api.client()).trigger(
            ROUTINE_ID, parameters={"a": {"b": {"c": {}}}}
        )
    assert exc.value.status_code == 422


# --- event triggers ----------------------------------------------------

TRIGGER_ID = "0199a1b2-0000-7000-8000-0000000000e1"

WEBHOOK_TRIGGER: dict[str, Any] = {
    "id": TRIGGER_ID,
    "routine_id": ROUTINE_ID,
    "org_id": ORG_ID,
    "project_id": PROJECT_ID,
    "source": "connector",
    "provider": "webhook",
    "connector_slug": "orders",
    "event_types": ["order.created"],
    "filter": {
        "channel_ids": None,
        "emoji": None,
        "team_ids": None,
        "to_states": None,
        "repository_ids": None,
        "branches": None,
        "payload_fields": {"region": ["eu"]},
    },
    "parameters": {"order_id": "/data/id"},
    "enabled": True,
    "created_at": "2026-11-01T10:00:00Z",
    "updated_at": "2026-11-01T10:00:00Z",
    "deleted_at": None,
}


def test_create_sends_triggers_and_decodes_them(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/routines",
        status=201,
        json_body=routine_body(
            trigger_type="manual", triggers=[WEBHOOK_TRIGGER]
        ),
    )

    created = Routines(fake_api.client()).create(
        name="Order follow-up",
        trigger_type="manual",
        prompt="Follow up on order @parameters.order_id",
        runtime_group_id=UUID(RUNTIME_GROUP_ID),
        triggers=[
            RoutineTriggerSpec(
                source=RoutineTriggerSource.CONNECTOR,
                provider=RoutineTriggerProvider.WEBHOOK,
                connector_slug="orders",
                event_types=["order.created"],
                filter=RoutineTriggerFilter(payload_fields={"region": ["eu"]}),
                parameters={"order_id": "/data/id"},
            ),
            {
                "provider": "github",
                "event_types": ["github.push"],
                "filter": {"branches": ["main"]},
            },
        ],
    )

    assert fake_api.last_request.json() == {
        "name": "Order follow-up",
        "trigger_type": "manual",
        "prompt": "Follow up on order @parameters.order_id",
        "runtime_group_id": RUNTIME_GROUP_ID,
        "triggers": [
            {
                "source": "connector",
                "provider": "webhook",
                "connector_slug": "orders",
                "event_types": ["order.created"],
                "filter": {"payload_fields": {"region": ["eu"]}},
                "parameters": {"order_id": "/data/id"},
            },
            {
                "provider": "github",
                "event_types": ["github.push"],
                "filter": {"branches": ["main"]},
            },
        ],
    }
    (trigger,) = created.triggers
    assert trigger.id == UUID(TRIGGER_ID)
    assert trigger.source is RoutineTriggerSource.CONNECTOR
    assert trigger.provider is RoutineTriggerProvider.WEBHOOK
    assert trigger.connector_slug == "orders"
    assert trigger.filter.payload_fields == {"region": ["eu"]}
    assert trigger.filter.channel_ids is None
    assert trigger.parameters == {"order_id": "/data/id"}
    assert trigger.enabled is True


def test_a_routine_without_triggers_reads_an_empty_list(fake_api: FakeAPI):
    fake_api.add("GET", ROUTINE_PATH, json_body=routine_body())

    assert Routines(fake_api.client()).get(ROUTINE_ID).triggers == []


def test_trigger_decodes_an_unknown_source_and_provider(fake_api: FakeAPI):
    future = {
        **WEBHOOK_TRIGGER,
        "source": "schedule_from_the_future",
        "provider": "jira",
        "filter": {},
    }
    fake_api.add(
        "GET", ROUTINE_PATH, json_body=routine_body(triggers=[future])
    )

    (trigger,) = Routines(fake_api.client()).get(ROUTINE_ID).triggers

    assert trigger.source == "schedule_from_the_future"
    assert trigger.provider == "jira"
    assert trigger.filter == RoutineTriggerFilter()


@pytest.mark.parametrize(
    ("triggers", "body"),
    [
        # A listed id keeps that trigger; the rest are removed.
        (
            [
                {
                    "id": TRIGGER_ID,
                    "provider": "webhook",
                    "source": "connector",
                    "connector_slug": "orders",
                    "event_types": ["*"],
                    "enabled": False,
                }
            ],
            [
                {
                    "id": TRIGGER_ID,
                    "provider": "webhook",
                    "source": "connector",
                    "connector_slug": "orders",
                    "event_types": ["*"],
                    "enabled": False,
                }
            ],
        ),
        # An empty list removes every trigger, so it is sent.
        ([], []),
    ],
)
def test_update_replaces_the_trigger_list(
    fake_api: FakeAPI, triggers: list[Any], body: list[Any]
):
    fake_api.add("PATCH", ROUTINE_PATH, json_body=routine_body())

    Routines(fake_api.client()).update(ROUTINE_ID, triggers=triggers)

    assert fake_api.last_request.json() == {"triggers": body}


async def test_async_crud_and_trigger(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/routines",
        paged_handler(
            [
                page([routine_body()], next="cur-2"),
                page([routine_body(name="second")]),
            ]
        ),
    )
    fake_api.add("GET", ROUTINE_PATH, json_body=routine_body())
    fake_api.add("POST", "/v1/routines", status=201, json_body=routine_body())
    fake_api.add("PATCH", ROUTINE_PATH, json_body=routine_body())
    fake_api.add("DELETE", ROUTINE_PATH, status=204)
    fake_api.add(
        "POST",
        f"{ROUTINE_PATH}/trigger",
        status=202,
        json_body={"status": "cancelled", "routine_id": ROUTINE_ID},
    )
    api = AsyncRoutines(fake_api.async_client())

    names = [a.name async for a in api.list(task_id=TASK_ID, enabled=True)]
    assert names == ["Weekly digest", "second"]
    assert [dict(r.params) for r in fake_api.requests] == [
        {"enabled": "true", "task_id": TASK_ID},
        {"enabled": "true", "task_id": TASK_ID, "next": "cur-2"},
    ]

    assert (await api.get(ROUTINE_ID)).name == "Weekly digest"

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

    await api.update(ROUTINE_ID, prompt="new")
    assert fake_api.last_request.json() == {"prompt": "new"}

    await api.delete(ROUTINE_ID)
    assert fake_api.last_request.method == "DELETE"

    result = await api.trigger(ROUTINE_ID)
    assert result.status is RoutineExecutionStatus.CANCELLED
    assert fake_api.last_request.content == b""

    await api.trigger(ROUTINE_ID, parameters={"ticket": 42})
    assert fake_api.last_request.json() == {"parameters": {"ticket": 42}}

    await api.update(
        ROUTINE_ID,
        triggers=[
            RoutineTriggerSpec(
                provider="slack",
                event_types=["slack.message.posted"],
                filter=RoutineTriggerFilter(channel_ids=["C1"]),
            )
        ],
    )
    assert fake_api.last_request.json() == {
        "triggers": [
            {
                "provider": "slack",
                "event_types": ["slack.message.posted"],
                "filter": {"channel_ids": ["C1"]},
            }
        ]
    }


# --- routine events ----------------------------------------------------

TRIGGERED_ROW: dict[str, Any] = {
    "id": "0199a1b2-0000-5000-8000-000000000001",
    "timestamp": "2026-10-05T09:00:02Z",
    "event_name": "introspection.routines.triggered",
    "conversation_id": "conv-1",
    "runtime_group_id": RUNTIME_GROUP_ID,
    "payload": {
        "routine_id": ROUTINE_ID,
        "routine_name": "Weekly digest",
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
    "event_name": "introspection.routines.skipped",
    "runtime_group_id": RUNTIME_GROUP_ID,
    "payload": {
        "routine_id": ROUTINE_ID,
        "trigger_type": "manual",
        "slot": "2026-10-06T09:00:00Z",
        "task_id": TASK_ID,
        "reason": "target_busy",
    },
}


def test_events_read_triggered_rows_with_routine_filters(
    fake_api: FakeAPI,
):
    fake_api.add("GET", "/v1/events", json_body=page([TRIGGERED_ROW]))

    events = list(
        Events(fake_api.client()).list(
            IntrospectionEventName.ROUTINE_TRIGGERED,
            routine_id=UUID(ROUTINE_ID),
            task_id=TASK_ID,
        )
    )

    params = fake_api.last_request.params
    assert params["event_name"] == "introspection.routines.triggered"
    assert params["routine_id"] == ROUTINE_ID
    assert params["task_id"] == TASK_ID

    (event,) = events
    assert isinstance(event, RoutineTriggeredEvent)
    run = event.payload
    assert run.routine_name == "Weekly digest"
    assert run.trigger_type is RoutineTriggerType.CRON
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
        .list("introspection.routines.skipped")
        .page()
        .records
    )

    assert isinstance(known, RoutineSkippedEvent)
    assert known.payload.reason is RoutineSkipReason.TARGET_BUSY
    assert known.payload.trigger_type is RoutineTriggerType.MANUAL
    assert known.payload.task_id == UUID(TASK_ID)
    assert isinstance(future, RoutineSkippedEvent)
    assert future.payload.reason == "reason_from_the_future"
    assert future.payload.task_id is None


EVENT_REF: dict[str, Any] = {
    "trigger_id": TRIGGER_ID,
    "event_type": "order.created",
    "delivery_id": "webhook:msg_2a",
}


def test_events_carry_the_trigger_that_started_or_skipped_a_run(
    fake_api: FakeAPI,
):
    started = {
        **TRIGGERED_ROW,
        "payload": {
            **TRIGGERED_ROW["payload"],
            "trigger_type": "manual",
            "slot": None,
            "posted": False,
            "event": EVENT_REF,
        },
    }
    busy = {
        **SKIPPED_ROW,
        "payload": {
            **SKIPPED_ROW["payload"],
            "slot": None,
            "task_id": None,
            "reason": "trigger_busy",
            "event": EVENT_REF,
        },
    }
    fake_api.add_handler(
        "GET",
        "/v1/events",
        paged_handler([page([started]), page([busy, SKIPPED_ROW])]),
    )
    events = Events(fake_api.client())

    (run,) = (
        events.list(IntrospectionEventName.ROUTINE_TRIGGERED).page().records
    )
    assert isinstance(run, RoutineTriggeredEvent)
    assert run.payload.event is not None
    assert run.payload.event.trigger_id == UUID(TRIGGER_ID)
    assert run.payload.event.event_type == "order.created"
    assert run.payload.event.delivery_id == "webhook:msg_2a"

    skipped, scheduled = (
        events.list(IntrospectionEventName.ROUTINE_SKIPPED).page().records
    )
    assert isinstance(skipped, RoutineSkippedEvent)
    assert skipped.payload.reason is RoutineSkipReason.TRIGGER_BUSY
    assert skipped.payload.event is not None
    assert skipped.payload.event.trigger_id == UUID(TRIGGER_ID)
    assert isinstance(scheduled, RoutineSkippedEvent)
    assert scheduled.payload.event is None


def test_run_source_names_the_trigger_source_values():
    assert [source.value for source in RoutineRunSource] == [
        "scheduled",
        "manual",
        "trigger",
    ]


def test_event_get_resolves_an_routine_family(fake_api: FakeAPI):
    fake_api.add(
        "GET", f"/v1/events/{SKIPPED_ROW['id']}", json_body=SKIPPED_ROW
    )

    event = Events(fake_api.client()).get(SKIPPED_ROW["id"])

    assert isinstance(event, RoutineSkippedEvent)


async def test_async_events_send_routine_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/events", json_body=page([TRIGGERED_ROW]))

    records = await AsyncEvents(fake_api.async_client()).list(
        IntrospectionEventName.ROUTINE_TRIGGERED,
        routine_id=ROUTINE_ID,
        task_id=UUID(TASK_ID),
    )

    assert isinstance(records.records[0], RoutineTriggeredEvent)
    params = fake_api.last_request.params
    assert params["routine_id"] == ROUTINE_ID
    assert params["task_id"] == TASK_ID


def test_create_rejects_a_naive_slot_before_sending(fake_api: FakeAPI):
    with pytest.raises(pydantic.ValidationError):
        Routines(fake_api.client()).create(
            name="One-off",
            trigger_type="manual",
            prompt="Go",
            runtime_group_id=UUID(RUNTIME_GROUP_ID),
            next_trigger_at=datetime(2026, 2, 1, 9, 0),
        )
    with pytest.raises(pydantic.ValidationError):
        Routines(fake_api.client()).update(
            ROUTINE_ID, next_trigger_at=datetime(2026, 2, 1, 9, 0)
        )
    assert fake_api.requests == []


def test_get_decodes_soft_delete_agent_and_operator_default(
    fake_api: FakeAPI,
):
    fake_api.add(
        "GET",
        ROUTINE_PATH,
        json_body=routine_body(
            deleted_at="2026-10-01T09:00:00Z",
            agent_member_id=MEMBER_ID,
            metadata={"operator_default": "project_check_in"},
        ),
    )

    routine = Routines(fake_api.client()).get(ROUTINE_ID)

    assert routine.deleted_at == datetime(2026, 10, 1, 9, tzinfo=UTC)
    assert routine.agent_member_id == UUID(MEMBER_ID)
    metadata = routine.typed_metadata
    assert metadata is not None
    assert metadata.operator_default == "project_check_in"
