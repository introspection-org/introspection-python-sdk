"""Contract tests for ``client.issues`` / ``runner.issues``.

Driven through the offline :class:`FakeAPI` transport from ``conftest.py``:
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
from introspection_sdk._errors import ConflictError
from introspection_sdk.runner_resources.issues import AsyncIssues, Issues
from introspection_sdk.schemas.issues import (
    IssueEventReference,
    IssueFile,
    IssueLink,
    IssueMutation,
    IssueOwner,
    IssuePriority,
    IssueRequestMutation,
    IssueRequestStatus,
    IssueSpanReference,
    IssueStatus,
    IssueUpdate,
)
from introspection_sdk.schemas.tasks import TaskStatus

from .conftest import (
    FILE_ID,
    MEMBER_ID,
    ORG_ID,
    PROJECT_ID,
    TASK_ID,
    FakeAPI,
)

ISSUE_ID = "0199a1b2-0000-7000-8000-0000000000e1"
ISSUE_PATH = f"/v1/issues/{ISSUE_ID}"
EVENT_ID = "0199a1b2-0000-7000-8000-0000000000e2"
REQUEST_ID = "0199a1b2-0000-7000-8000-0000000000e3"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"


def issue_body(**over: Any) -> dict[str, Any]:
    """Every field the DP ``Issue`` schema documents."""
    body: dict[str, Any] = {
        "id": ISSUE_ID,
        "org_id": ORG_ID,
        "project_id": PROJECT_ID,
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-02T11:00:00Z",
        "title": "Checkout times out",
        "description": "Stripe calls exceed 30s under load.",
        "priority": "high",
        "status": "waiting",
        "revision": 3,
        "files": [
            {
                "file_id": FILE_ID,
                "name": "trace.json",
                "checksum": "sha256:abc",
                "source_event_ids": [EVENT_ID],
            }
        ],
        "links": [
            {"url": "https://github.com/acme/app/pull/7", "title": "PR"}
        ],
        "events": [{"event_id": EVENT_ID}],
        "spans": [{"trace_id": TRACE_ID, "span_id": SPAN_ID}],
        "tags": ["customer:acme"],
        "metadata": {"severity": 2, "flaky": True, "ratio": 0.5, "x": None},
        "display_index": 42,
        "task_id": TASK_ID,
        "task_status": "awaiting_user",
        "member_id": None,
        "closed_at": None,
        "open_requests": [
            {
                "id": REQUEST_ID,
                "question": "Ship the retry?",
                "assignee_id": MEMBER_ID,
                "created_at": "2026-10-02T11:00:00Z",
            }
        ],
    }
    body.update(over)
    return body


def page(records: list[dict[str, Any]], next: str | None = None) -> dict:
    return {"records": records, "count": len(records), "next": next}


def paged_handler(pages: list[dict[str, Any]]):
    remaining = list(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remaining.pop(0))

    return handler


def test_client_exposes_issues_on_the_data_plane():
    client = IntrospectionClient(
        token="t", base_api_url="https://api.test", dp_url="https://dp.test"
    )
    try:
        assert isinstance(client.issues, Issues)
        assert client.issues._http is client._dp_http
    finally:
        client.shutdown()


async def test_async_client_exposes_issues():
    client = AsyncIntrospectionClient(
        token="t", base_api_url="https://api.test"
    )
    try:
        assert isinstance(client.issues, AsyncIssues)
    finally:
        await client.shutdown()


def test_get_decodes_every_documented_field(fake_api: FakeAPI):
    fake_api.add("GET", ISSUE_PATH, json_body=issue_body())

    issue = Issues(fake_api.client()).get(UUID(ISSUE_ID))

    assert fake_api.last_request.method == "GET"
    assert issue.model_extra == {}
    assert issue.id == UUID(ISSUE_ID)
    assert issue.priority is IssuePriority.HIGH
    assert issue.status is IssueStatus.WAITING
    assert issue.revision == 3
    assert issue.files == [
        IssueFile(
            file_id=UUID(FILE_ID),
            name="trace.json",
            checksum="sha256:abc",
            source_event_ids=[UUID(EVENT_ID)],
        )
    ]
    assert issue.links[0].url == "https://github.com/acme/app/pull/7"
    assert issue.events == [IssueEventReference(event_id=UUID(EVENT_ID))]
    assert issue.spans == [
        IssueSpanReference(trace_id=TRACE_ID, span_id=SPAN_ID)
    ]
    assert issue.metadata == {
        "severity": 2,
        "flaky": True,
        "ratio": 0.5,
        "x": None,
    }
    assert issue.display_index == 42
    assert issue.task_id == UUID(TASK_ID)
    assert issue.task_status is TaskStatus.AWAITING_USER
    assert issue.member_id is None
    assert issue.closed_at is None
    (request,) = issue.open_requests
    assert request.assignee_id == UUID(MEMBER_ID)
    assert request.created_at == datetime(2026, 10, 2, 11, tzinfo=UTC)


def test_minimal_issue_and_open_enums(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/issues/minimal",
        json_body={
            "id": ISSUE_ID,
            "org_id": ORG_ID,
            "project_id": PROJECT_ID,
            "title": "t",
            "description": "d",
            "status": "triaged",
            "priority": "someday",
            "task_status": "hibernating",
        },
    )

    issue = Issues(fake_api.client()).get("minimal")

    assert issue.status == "triaged"
    assert not isinstance(issue.status, IssueStatus)
    assert issue.priority == "someday"
    assert issue.task_status == "hibernating"
    assert issue.revision == 1
    assert issue.files == issue.links == issue.open_requests == []
    assert issue.metadata == {}


def test_list_repeats_params_and_paginates(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/issues",
        paged_handler(
            [
                page([issue_body()], next="cur-2"),
                page([issue_body(title="second")]),
            ]
        ),
    )

    titles = [
        issue.title
        for issue in Issues(fake_api.client()).list(
            status=[IssueStatus.OPEN, "waiting"],
            owner=[IssueOwner.PROJECT, IssueOwner.ME],
            assigned_to_me=True,
            has_open_requests=False,
            task_status=[TaskStatus.RUNNING, TaskStatus.IDLE],
            exclude_task_status=[TaskStatus.FAILED],
            display_index=42,
            tag="customer:acme",
            metadata={"severity": "2", "team": "payments"},
            include_total=True,
            limit=1,
        )
    ]

    assert titles == ["Checkout times out", "second"]
    first, second = fake_api.requests
    assert first.path == "/v1/issues"
    assert first.params.multi_items() == [
        ("limit", "1"),
        ("status", "open"),
        ("status", "waiting"),
        ("owner", "project"),
        ("owner", "me"),
        ("assigned_to_me", "true"),
        ("has_open_requests", "false"),
        ("task_status", "running"),
        ("task_status", "idle"),
        ("exclude_task_status", "failed"),
        ("display_index", "42"),
        ("tag", "customer:acme"),
        ("metadata", "severity:2"),
        ("metadata", "team:payments"),
        ("include_total", "true"),
    ]
    assert second.params["next"] == "cur-2"
    assert second.params.get_list("status") == ["open", "waiting"]


def test_list_reads_total_count_and_omits_unset_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/issues",
        json_body={**page([issue_body()]), "total_count": 7},
    )

    result = Issues(fake_api.client()).list(next="cur-9").page()

    assert dict(fake_api.last_request.params) == {"next": "cur-9"}
    assert result.total_count == 7
    assert result.records[0].title == "Checkout times out"


def test_create_sends_the_body_and_idempotency_key(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/issues", status=201, json_body=issue_body())

    issue = Issues(fake_api.client()).create(
        title="Checkout times out",
        description="Stripe calls exceed 30s under load.",
        task_id=TASK_ID,
        priority=IssuePriority.HIGH,
        links=[IssueLink(url="https://github.com/acme/app/pull/7")],
        spans=[IssueSpanReference(trace_id=TRACE_ID, span_id=SPAN_ID)],
        tags=["customer:acme"],
        metadata={"severity": 2},
        idempotency_key="create-1",
    )

    assert issue.id == UUID(ISSUE_ID)
    sent = fake_api.last_request
    assert (sent.method, sent.path) == ("POST", "/v1/issues")
    assert sent.headers["Idempotency-Key"] == "create-1"
    assert sent.json() == {
        "title": "Checkout times out",
        "description": "Stripe calls exceed 30s under load.",
        "task_id": TASK_ID,
        "priority": "high",
        "links": [{"url": "https://github.com/acme/app/pull/7"}],
        "spans": [{"trace_id": TRACE_ID, "span_id": SPAN_ID}],
        "tags": ["customer:acme"],
        "metadata": {"severity": 2},
    }


def test_create_without_a_key_sends_no_header(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/issues", status=201, json_body=issue_body())

    Issues(fake_api.client()).create(
        title="t", description="d", task_id=TASK_ID
    )

    assert "Idempotency-Key" not in fake_api.last_request.headers
    assert fake_api.last_request.json() == {
        "title": "t",
        "description": "d",
        "task_id": TASK_ID,
    }


def test_create_validates_before_sending(fake_api: FakeAPI):
    with pytest.raises(pydantic.ValidationError):
        Issues(fake_api.client()).create(
            title="", description="d", task_id=TASK_ID
        )
    assert fake_api.requests == []


def test_update_sends_only_set_fields(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body(revision=4))

    issue = Issues(fake_api.client()).update(
        ISSUE_ID,
        IssueUpdate(
            expected_revision=3,
            status=IssueStatus.CLOSED,
            links=[IssueLink(url="https://x.test", title="fix")],
        ),
        idempotency_key="close-1",
    )

    assert issue.revision == 4
    sent = fake_api.last_request
    assert (sent.method, sent.path) == ("PATCH", ISSUE_PATH)
    assert sent.headers["Idempotency-Key"] == "close-1"
    assert sent.json() == {
        "expected_revision": 3,
        "status": "closed",
        "links": [{"url": "https://x.test", "title": "fix"}],
    }


def test_update_sends_an_empty_list_and_an_explicit_null(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body())

    Issues(fake_api.client()).update(
        ISSUE_ID,
        IssueUpdate(
            expected_revision=3, tags=[], files=[], metadata={}, priority=None
        ),
    )

    assert "Idempotency-Key" not in fake_api.last_request.headers
    assert fake_api.last_request.json() == {
        "expected_revision": 3,
        "tags": [],
        "files": [],
        "metadata": {},
        "priority": None,
    }


def test_update_creates_a_request(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body())

    Issues(fake_api.client()).update(
        ISSUE_ID,
        IssueMutation(
            request=IssueRequestMutation(
                id=UUID(REQUEST_ID),
                expected_revision=0,
                question="Ship the retry?",
                assignee_id=UUID(MEMBER_ID),
            )
        ),
        idempotency_key="ask-1",
    )

    sent = fake_api.last_request
    assert sent.headers["Idempotency-Key"] == "ask-1"
    assert sent.json() == {
        "request": {
            "id": REQUEST_ID,
            "expected_revision": 0,
            "question": "Ship the retry?",
            "assignee_id": MEMBER_ID,
        }
    }


def test_update_resolves_a_request(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body(open_requests=[]))

    issue = Issues(fake_api.client()).update(
        ISSUE_ID,
        IssueMutation(
            request=IssueRequestMutation(
                id=UUID(REQUEST_ID),
                expected_revision=2,
                status=IssueRequestStatus.RESOLVED,
                resolution="Shipped in #7",
            )
        ),
    )

    assert issue.open_requests == []
    assert fake_api.last_request.json() == {
        "request": {
            "id": REQUEST_ID,
            "expected_revision": 2,
            "status": "resolved",
            "resolution": "Shipped in #7",
        }
    }


def test_a_new_request_mints_a_uuid7():
    mutation = IssueRequestMutation(
        expected_revision=0, question="q", assignee_id=UUID(MEMBER_ID)
    )

    assert mutation.id.version == 7
    body = mutation.model_dump(mode="json", exclude_none=True)
    assert body["id"] == str(mutation.id)


def test_request_models_reject_what_the_server_refuses():
    with pytest.raises(pydantic.ValidationError, match="at least one field"):
        IssueUpdate(expected_revision=1)
    with pytest.raises(pydantic.ValidationError):
        IssueUpdate(expected_revision=0, title="t")
    with pytest.raises(pydantic.ValidationError, match="question"):
        IssueRequestMutation(expected_revision=0, assignee_id=UUID(MEMBER_ID))
    with pytest.raises(pydantic.ValidationError):
        IssueMutation.model_validate({"request": {}, "extra": 1})
    with pytest.raises(pydantic.ValidationError):
        IssueSpanReference(trace_id="nothex", span_id=SPAN_ID)


def test_a_stale_revision_raises_conflict(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        ISSUE_PATH,
        status=409,
        json_body={"detail": "stale revision"},
    )

    with pytest.raises(ConflictError):
        Issues(fake_api.client()).update(
            ISSUE_ID, IssueUpdate(expected_revision=1, title="t")
        )


def test_delete_sends_the_idempotency_key(fake_api: FakeAPI):
    fake_api.add("DELETE", ISSUE_PATH, status=204)
    api = Issues(fake_api.client())

    assert api.delete(ISSUE_ID, idempotency_key="rm-1") is None
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.headers["Idempotency-Key"] == "rm-1"

    api.delete(UUID(ISSUE_ID))
    assert "Idempotency-Key" not in fake_api.last_request.headers


async def test_async_issues_cover_every_operation(fake_api: FakeAPI):
    fake_api.add_handler(
        "GET",
        "/v1/issues",
        paged_handler(
            [
                page([issue_body()], next="c2"),
                page([issue_body()], next="c2"),
                page([issue_body()]),
            ]
        ),
    )
    fake_api.add("GET", ISSUE_PATH, json_body=issue_body())
    fake_api.add("POST", "/v1/issues", status=201, json_body=issue_body())
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body())
    fake_api.add("DELETE", ISSUE_PATH, status=204)
    api = AsyncIssues(fake_api.async_client())

    first = await api.list(status=[IssueStatus.OPEN])
    assert first.next == "c2"
    listed = [issue async for issue in api.list(owner=[IssueOwner.ME])]
    assert len(listed) == 2
    assert (await api.get(ISSUE_ID)).title == "Checkout times out"
    created = await api.create(
        title="t", description="d", task_id=TASK_ID, idempotency_key="k1"
    )
    assert created.id == UUID(ISSUE_ID)
    await api.update(
        ISSUE_ID,
        IssueUpdate(expected_revision=3, events=[]),
        idempotency_key="k2",
    )
    await api.update(
        ISSUE_ID,
        IssueMutation(
            request=IssueRequestMutation(
                id=UUID(REQUEST_ID),
                expected_revision=1,
                status=IssueRequestStatus.CANCELLED,
                resolution="Not needed",
            )
        ),
    )
    await api.delete(ISSUE_ID, idempotency_key="k3")

    calls = [
        (r.method, r.path, r.headers.get("Idempotency-Key"))
        for r in fake_api.requests
    ]
    assert calls == [
        ("GET", "/v1/issues", None),
        ("GET", "/v1/issues", None),
        ("GET", "/v1/issues", None),
        ("GET", ISSUE_PATH, None),
        ("POST", "/v1/issues", "k1"),
        ("PATCH", ISSUE_PATH, "k2"),
        ("PATCH", ISSUE_PATH, None),
        ("DELETE", ISSUE_PATH, "k3"),
    ]
    assert fake_api.requests[0].params.get_list("status") == ["open"]
    assert fake_api.requests[1].params.get_list("owner") == ["me"]
    assert fake_api.requests[5].json() == {
        "expected_revision": 3,
        "events": [],
    }
    assert fake_api.requests[6].json() == {
        "request": {
            "id": REQUEST_ID,
            "expected_revision": 1,
            "status": "cancelled",
            "resolution": "Not needed",
        }
    }
