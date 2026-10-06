"""Contract tests for ``client.issues`` / ``runner.issues`` (DP ``/v1/issues``).

Driven through the offline :class:`FakeAPI` transport from ``conftest.py`` —
nothing in ``introspection_sdk`` is patched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest

from introspection_sdk._errors import ConflictError
from introspection_sdk.runner_resources import AsyncIssues, Issues
from introspection_sdk.schemas.issues import (
    IssueEventReference,
    IssueLink,
    IssueOwner,
    IssuePriority,
    IssueStatus,
)
from introspection_sdk.schemas.tasks import TaskStatus

from .conftest import (
    ISSUE_ID,
    MEMBER_ID,
    TASK_ID,
    FakeAPI,
    issue_payload,
    paginated,
    to_jsonable,
)

ISSUE_PATH = f"/v1/issues/{ISSUE_ID}"
EVENT_ID = "0199a1b2-0000-7000-8000-0000000000f1"


def test_get_decodes_the_issue(fake_api: FakeAPI):
    body = to_jsonable(issue_payload())
    body["member_id"] = MEMBER_ID
    body["closed_at"] = None
    body["open_requests"] = [
        {
            "id": EVENT_ID,
            "question": "Which PSP?",
            "assignee_id": MEMBER_ID,
            "created_at": "2026-10-01T09:00:00Z",
        }
    ]
    body["links"] = [{"url": "https://status.example/1", "title": None}]
    fake_api.add("GET", ISSUE_PATH, json_body=body)

    issue = Issues(fake_api.client()).get(UUID(ISSUE_ID))

    assert fake_api.last_request.method == "GET"
    assert issue.id == UUID(ISSUE_ID)
    assert issue.priority is IssuePriority.HIGH
    assert issue.status is IssueStatus.OPEN
    assert issue.task_status is TaskStatus.IDLE
    assert issue.revision == 3
    assert issue.display_index == 42
    assert issue.member_id == UUID(MEMBER_ID)
    assert issue.metadata == {"severity": "sev2"}
    assert issue.links[0].url == "https://status.example/1"
    request = issue.open_requests[0]
    assert request.question == "Which PSP?"
    assert request.created_at == datetime(2026, 10, 1, 9, tzinfo=UTC)


def test_unknown_status_and_priority_decode_as_strings(fake_api: FakeAPI):
    body = to_jsonable(issue_payload())
    body.update(status="snoozed", priority="whenever", task_status="paused")
    body["open_requests"] = None
    fake_api.add("GET", ISSUE_PATH, json_body=body)

    issue = Issues(fake_api.client()).get(ISSUE_ID)

    assert issue.status == "snoozed"
    assert not isinstance(issue.status, IssueStatus)
    assert issue.priority == "whenever"
    assert issue.task_status == "paused"
    assert issue.open_requests == []


def test_list_sends_every_filter_and_follows_the_cursor(fake_api: FakeAPI):
    pages = [
        paginated([issue_payload()], next="cur-2", total_count=2),
        paginated([issue_payload(title="second")], total_count=2),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=to_jsonable(pages.pop(0)))

    fake_api.add_handler("GET", "/v1/issues", handler)

    titles = [
        issue.title
        for issue in Issues(fake_api.client()).list(
            status=[IssueStatus.OPEN, "waiting"],
            owner=[IssueOwner.ME],
            assigned_to_me=True,
            has_open_requests=False,
            task_status=[TaskStatus.RUNNING],
            exclude_task_status=["failed", TaskStatus.CANCELLED],
            display_index=42,
            tag="customer:acme",
            metadata={"severity": "sev2", "region": "eu"},
            search="checkout",
            include_total=True,
            limit=10,
        )
    ]

    assert titles == ["Checkout fails for EU cards", "second"]
    first, second = (r.params for r in fake_api.requests)
    assert first.get_list("status") == ["open", "waiting"]
    assert first.get_list("owner") == ["me"]
    assert first["assigned_to_me"] == "true"
    assert first["has_open_requests"] == "false"
    assert first.get_list("task_status") == ["running"]
    assert first.get_list("exclude_task_status") == ["failed", "cancelled"]
    assert first["display_index"] == "42"
    assert first["tag"] == "customer:acme"
    assert first.get_list("metadata") == ["severity:sev2", "region:eu"]
    assert first["search"] == "checkout"
    assert first["include_total"] == "true"
    assert first["limit"] == "10"
    assert "next" not in first
    assert second["next"] == "cur-2"
    assert second.get_list("status") == ["open", "waiting"]


def test_list_without_filters_sends_none(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/issues", json_body=paginated([]))

    page = Issues(fake_api.client()).list().page()

    assert page.count == 0
    assert dict(fake_api.last_request.params) == {}


def test_create_sends_the_brief_and_idempotency_key(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/issues", status=201, json_body=issue_payload())

    issue = Issues(fake_api.client()).create(
        title="Checkout fails for EU cards",
        description="Card payments decline at 3DS.",
        task_id=TASK_ID,
        priority="high",
        tags=["customer:acme"],
        metadata={"severity": "sev2", "count": 3},
        links=[IssueLink(url="https://status.example/1")],
        events=[IssueEventReference(event_id=UUID(EVENT_ID))],
        idempotency_key="attempt-1",
    )

    assert issue.id == UUID(ISSUE_ID)
    request = fake_api.last_request
    assert request.method == "POST"
    assert request.headers["idempotency-key"] == "attempt-1"
    assert request.json() == {
        "title": "Checkout fails for EU cards",
        "description": "Card payments decline at 3DS.",
        "task_id": TASK_ID,
        "priority": "high",
        "tags": ["customer:acme"],
        "metadata": {"severity": "sev2", "count": 3},
        "links": [{"url": "https://status.example/1"}],
        "events": [{"event_id": EVENT_ID}],
    }


def test_update_sends_only_set_fields_and_can_clear(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_payload(revision=4))

    issue = Issues(fake_api.client()).update(
        ISSUE_ID,
        expected_revision=3,
        status=IssueStatus.CLOSED,
        tags=[],
        metadata={},
    )

    assert issue.revision == 4
    assert fake_api.last_request.method == "PATCH"
    assert "idempotency-key" not in fake_api.last_request.headers
    assert fake_api.last_request.json() == {
        "expected_revision": 3,
        "status": "closed",
        "tags": [],
        "metadata": {},
    }


def test_update_at_a_stale_revision_is_a_conflict(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        ISSUE_PATH,
        status=409,
        json_body={"detail": "Issue revision changed"},
    )

    with pytest.raises(ConflictError):
        Issues(fake_api.client()).update(
            ISSUE_ID, expected_revision=1, title="t"
        )


def test_delete_escapes_the_id_and_returns_none(fake_api: FakeAPI):
    fake_api.add("DELETE", "/v1/issues/a/b", status=204)

    assert Issues(fake_api.client()).delete("a/b", idempotency_key="k") is None
    assert fake_api.last_request.url.raw_path == b"/v1/issues/a%2Fb"
    assert fake_api.last_request.headers["idempotency-key"] == "k"


async def test_async_crud(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/issues",
        json_body=paginated([issue_payload(), issue_payload(title="b")]),
    )
    fake_api.add("GET", ISSUE_PATH, json_body=issue_payload())
    fake_api.add("POST", "/v1/issues", status=201, json_body=issue_payload())
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_payload(revision=4))
    fake_api.add("DELETE", ISSUE_PATH, status=204)
    api = AsyncIssues(fake_api.async_client())

    titles = [i.title async for i in api.list(owner=["project"])]
    assert titles == ["Checkout fails for EU cards", "b"]
    assert fake_api.last_request.params.get_list("owner") == ["project"]

    assert (await api.get(ISSUE_ID)).revision == 3
    await api.create(
        title="t", description="d", task_id=UUID(TASK_ID), idempotency_key="i"
    )
    assert fake_api.last_request.json() == {
        "title": "t",
        "description": "d",
        "task_id": TASK_ID,
    }
    assert fake_api.last_request.headers["idempotency-key"] == "i"
    updated = await api.update(
        ISSUE_ID, expected_revision=3, priority=IssuePriority.URGENT
    )
    assert updated.revision == 4
    assert fake_api.last_request.json() == {
        "expected_revision": 3,
        "priority": "urgent",
    }
    assert await api.delete(UUID(ISSUE_ID)) is None
    assert [r.method for r in fake_api.requests] == [
        "GET",
        "GET",
        "POST",
        "PATCH",
        "DELETE",
    ]
