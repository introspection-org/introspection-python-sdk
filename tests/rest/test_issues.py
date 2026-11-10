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
from introspection_sdk._errors import (
    ConflictError,
    IntrospectionAPIError,
    NotFoundError,
)
from introspection_sdk.runner_resources.issues import AsyncIssues, Issues
from introspection_sdk.schemas.issues import (
    Issue,
    IssueEventReference,
    IssueFile,
    IssueLink,
    IssueMember,
    IssueMemberRelation,
    IssueOwner,
    IssuePriority,
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
COMMENT_ID = "0199a1b2-0000-7000-8000-0000000000e3"
REVIEWER_ID = "0199a1b2-0000-7000-8000-0000000000e4"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"


ATTACHMENTS: dict[str, Any] = {
    "files": [
        {
            "file_id": FILE_ID,
            "name": "trace.json",
            "checksum": "sha256:abc",
            "source_event_ids": [EVENT_ID],
        }
    ],
    "links": [{"url": "https://github.com/acme/app/pull/7", "title": "PR"}],
    "events": [{"event_id": EVENT_ID}],
    "spans": [{"trace_id": TRACE_ID, "span_id": SPAN_ID}],
}
MEMBERS: dict[str, Any] = {
    "members": [
        {"member_id": MEMBER_ID, "relation": "creator"},
        {"member_id": MEMBER_ID, "relation": "assignee"},
        {"member_id": REVIEWER_ID, "relation": "reviewer"},
    ]
}
COMMENT: dict[str, Any] = {
    "id": COMMENT_ID,
    "issue_id": ISSUE_ID,
    "comment": "Ship the retry?",
    "member_id": MEMBER_ID,
    "actor_member_id": None,
    "actor_member_type": None,
    "created_at": "2026-10-02T11:30:00Z",
}


def issue_body(**over: Any) -> dict[str, Any]:
    """The brief the DP ``Issue`` schema returns: every list not included
    is null."""
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
        "tags": ["customer:acme"],
        "metadata": {"severity": 2, "flaky": True, "ratio": 0.5, "x": None},
        "display_index": 42,
        "task_id": TASK_ID,
        "task_status": "awaiting_user",
        "member_id": None,
        "created_by_member_id": MEMBER_ID,
        "assignee_member_id": MEMBER_ID,
        "reviewer_member_id": None,
        "closed_at": None,
        "members": None,
        "links": None,
        "files": None,
        "events": None,
        "spans": None,
        "comments": None,
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


def test_get_decodes_the_brief_and_leaves_the_lists_none(fake_api: FakeAPI):
    fake_api.add("GET", ISSUE_PATH, json_body=issue_body())

    issue = Issues(fake_api.client()).get(UUID(ISSUE_ID))

    assert fake_api.last_request.method == "GET"
    assert "include" not in fake_api.last_request.params
    assert issue.model_extra == {}
    assert issue.id == UUID(ISSUE_ID)
    assert issue.priority is IssuePriority.HIGH
    assert issue.status is IssueStatus.WAITING
    assert issue.revision == 3
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
    assert issue.created_by_member_id == UUID(MEMBER_ID)
    assert issue.assignee_member_id == UUID(MEMBER_ID)
    assert issue.reviewer_member_id is None
    assert issue.closed_at is None
    assert issue.created_at == datetime(2026, 10, 1, 10, tzinfo=UTC)
    assert (issue.members, issue.comments) == (None, None)
    assert (issue.links, issue.files, issue.events, issue.spans) == (
        None,
        None,
        None,
        None,
    )


def test_get_includes_members(fake_api: FakeAPI):
    fake_api.add("GET", ISSUE_PATH, json_body=issue_body(**MEMBERS))

    issue = Issues(fake_api.client()).get(ISSUE_ID, include=["members"])

    assert fake_api.last_request.params.get_list("include") == ["members"]
    assert issue.members == [
        IssueMember(
            member_id=UUID(MEMBER_ID), relation=IssueMemberRelation.CREATOR
        ),
        IssueMember(
            member_id=UUID(MEMBER_ID), relation=IssueMemberRelation.ASSIGNEE
        ),
        IssueMember(
            member_id=UUID(REVIEWER_ID), relation=IssueMemberRelation.REVIEWER
        ),
    ]
    assert issue.files is None


def test_get_includes_attachments(fake_api: FakeAPI):
    fake_api.add("GET", ISSUE_PATH, json_body=issue_body(**ATTACHMENTS))

    issue = Issues(fake_api.client()).get(ISSUE_ID, include=["attachments"])

    assert fake_api.last_request.params.get_list("include") == ["attachments"]
    assert issue.files == [
        IssueFile(
            file_id=UUID(FILE_ID),
            name="trace.json",
            checksum="sha256:abc",
            source_event_ids=[UUID(EVENT_ID)],
        )
    ]
    assert issue.links is not None
    assert issue.links[0].url == "https://github.com/acme/app/pull/7"
    assert issue.events == [IssueEventReference(event_id=UUID(EVENT_ID))]
    assert issue.spans == [
        IssueSpanReference(trace_id=TRACE_ID, span_id=SPAN_ID)
    ]
    assert issue.members is None


def test_get_includes_comments(fake_api: FakeAPI):
    agent_comment = {
        **COMMENT,
        "comment": "Retry shipped.",
        "actor_member_id": REVIEWER_ID,
        "actor_member_type": "agent",
    }
    fake_api.add(
        "GET",
        ISSUE_PATH,
        json_body=issue_body(comments=[COMMENT, agent_comment]),
    )

    issue = Issues(fake_api.client()).get(
        ISSUE_ID, include=["members", "comments"]
    )

    assert fake_api.last_request.params.get_list("include") == [
        "members",
        "comments",
    ]
    assert issue.comments is not None
    first, second = issue.comments
    assert (first.id, first.issue_id) == (UUID(COMMENT_ID), UUID(ISSUE_ID))
    assert (first.comment, first.member_id) == (
        "Ship the retry?",
        UUID(MEMBER_ID),
    )
    assert first.actor_member_id is None
    assert (second.actor_member_id, second.actor_member_type) == (
        UUID(REVIEWER_ID),
        "agent",
    )


def test_open_enums_decode_an_unknown_value(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        ISSUE_PATH,
        json_body=issue_body(
            status="triaged",
            priority="someday",
            task_status="hibernating",
            members=[{"member_id": MEMBER_ID, "relation": "watcher"}],
        ),
    )

    issue = Issues(fake_api.client()).get(ISSUE_ID)

    assert issue.status == "triaged"
    assert not isinstance(issue.status, IssueStatus)
    assert issue.priority == "someday"
    assert issue.task_status == "hibernating"
    assert issue.members is not None
    assert issue.members[0].relation == "watcher"


def test_an_issue_without_a_field_the_server_always_sends_does_not_decode():
    body = issue_body()
    del body["revision"]

    with pytest.raises(pydantic.ValidationError):
        Issue.model_validate(body)


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
            relation=[IssueMemberRelation.ASSIGNEE, "reviewer"],
            member_id=UUID(MEMBER_ID),
            include=["members", "attachments"],
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
        ("relation", "assignee"),
        ("relation", "reviewer"),
        ("member_id", MEMBER_ID),
        ("include", "members"),
        ("include", "attachments"),
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


def test_create_sends_the_body(fake_api: FakeAPI):
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
    )

    assert issue.id == UUID(ISSUE_ID)
    sent = fake_api.last_request
    assert (sent.method, sent.path) == ("POST", "/v1/issues")
    assert "If-Match" not in sent.headers
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


def test_create_sets_the_people_and_asks_for_lists(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/issues",
        status=201,
        json_body=issue_body(**MEMBERS, **ATTACHMENTS),
    )

    issue = Issues(fake_api.client()).create(
        title="t",
        description="d",
        task_id=TASK_ID,
        assignee_member_id=MEMBER_ID,
        reviewer_member_id=UUID(REVIEWER_ID),
        follower_member_ids=[UUID(REVIEWER_ID)],
        include=["members", "attachments"],
    )

    sent = fake_api.last_request
    assert sent.params.get_list("include") == ["members", "attachments"]
    assert sent.json() == {
        "title": "t",
        "description": "d",
        "task_id": TASK_ID,
        "assignee_member_id": MEMBER_ID,
        "reviewer_member_id": REVIEWER_ID,
        "follower_member_ids": [REVIEWER_ID],
    }
    assert issue.members is not None
    assert issue.files is not None


def test_create_omits_unset_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/issues", status=201, json_body=issue_body())

    Issues(fake_api.client()).create(
        title="t", description="d", task_id=TASK_ID
    )

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
            status=IssueStatus.CLOSED,
            links=[IssueLink(url="https://x.test", title="fix")],
        ),
    )

    assert issue.revision == 4
    sent = fake_api.last_request
    assert (sent.method, sent.path) == ("PATCH", ISSUE_PATH)
    assert "If-Match" not in sent.headers
    assert sent.json() == {
        "status": "closed",
        "links": [{"url": "https://x.test", "title": "fix"}],
    }


def test_update_clears_a_person_with_null_and_leaves_an_omitted_one(
    fake_api: FakeAPI,
):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body(**MEMBERS))
    api = Issues(fake_api.client())

    issue = api.update(
        ISSUE_ID,
        IssueUpdate(
            assignee_member_id=None,
            reviewer_member_id=UUID(REVIEWER_ID),
            follower_member_ids=[],
        ),
        include=["members"],
    )

    sent = fake_api.last_request
    assert sent.json() == {
        "assignee_member_id": None,
        "reviewer_member_id": REVIEWER_ID,
        "follower_member_ids": [],
    }
    assert sent.params.get_list("include") == ["members"]
    assert issue.members is not None

    api.update(ISSUE_ID, IssueUpdate(status=IssueStatus.WAITING))
    assert fake_api.last_request.json() == {"status": "waiting"}
    assert "include" not in fake_api.last_request.params


def test_update_sends_an_empty_list_and_an_explicit_null(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body())

    Issues(fake_api.client()).update(
        ISSUE_ID,
        IssueUpdate(tags=[], files=[], metadata={}, priority=None),
    )

    assert fake_api.last_request.json() == {
        "tags": [],
        "files": [],
        "metadata": {},
        "priority": None,
    }


def test_an_empty_update_sends_an_empty_body(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body())

    Issues(fake_api.client()).update(ISSUE_ID, IssueUpdate())

    assert fake_api.last_request.json() == {}


def test_request_models_reject_what_the_server_refuses():
    with pytest.raises(pydantic.ValidationError):
        IssueUpdate.model_validate({"expected_revision": 1, "title": "t"})
    # The request body the server removed.
    with pytest.raises(pydantic.ValidationError):
        IssueUpdate.model_validate({"request": {"question": "q"}})
    with pytest.raises(pydantic.ValidationError):
        IssueUpdate(follower_member_ids=[UUID(MEMBER_ID)] * 51)
    with pytest.raises(pydantic.ValidationError):
        IssueSpanReference(trace_id="nothex", span_id=SPAN_ID)


def test_comment_create_posts_the_comment(fake_api: FakeAPI):
    fake_api.add(
        "POST", f"{ISSUE_PATH}/comments", status=201, json_body=COMMENT
    )

    comment = Issues(fake_api.client()).comments.create(
        UUID(ISSUE_ID), comment="Ship the retry?"
    )

    sent = fake_api.last_request
    assert (sent.method, sent.path) == ("POST", f"{ISSUE_PATH}/comments")
    assert sent.json() == {"comment": "Ship the retry?"}
    assert comment.id == UUID(COMMENT_ID)
    assert comment.issue_id == UUID(ISSUE_ID)
    assert comment.member_id == UUID(MEMBER_ID)
    assert comment.created_at == datetime(2026, 10, 2, 11, 30, tzinfo=UTC)
    assert comment.model_extra == {}


def test_comment_create_surfaces_a_refusal(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"{ISSUE_PATH}/comments",
        status=404,
        json_body={"detail": "Issue not found"},
    )

    with pytest.raises(NotFoundError):
        Issues(fake_api.client()).comments.create(ISSUE_ID, comment="hi")


def test_etag_is_updated_at_in_quoted_iso_8601():
    issue = Issue.model_validate(
        issue_body(updated_at="2026-11-04T01:00:00.123456Z")
    )
    assert issue.etag == '"2026-11-04T01:00:00.123456+00:00"'

    # The offset is kept and the microseconds are not truncated.
    issue = Issue.model_validate(
        issue_body(updated_at="2026-11-04T02:00:00.000001+01:00")
    )
    assert issue.etag == '"2026-11-04T02:00:00.000001+01:00"'

    # A naive timestamp is read as UTC.
    naive = Issue.model_validate(
        issue_body(updated_at=datetime(2026, 11, 4, 1, 0, 0, 5))
    )
    assert naive.etag == '"2026-11-04T01:00:00.000005+00:00"'


def test_update_sends_if_match_only_when_given(fake_api: FakeAPI):
    fake_api.add("PATCH", ISSUE_PATH, json_body=issue_body())
    api = Issues(fake_api.client())
    issue = Issue.model_validate(issue_body())

    api.update(ISSUE_ID, IssueUpdate(title="t"), if_match=issue.etag)
    sent = fake_api.last_request
    assert sent.headers["If-Match"] == '"2026-10-02T11:00:00+00:00"'
    assert sent.json() == {"title": "t"}

    api.update(ISSUE_ID, IssueUpdate(title="t"))
    assert "If-Match" not in fake_api.last_request.headers


def test_a_stale_if_match_raises_precondition_failed(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        ISSUE_PATH,
        status=412,
        json_body={"detail": "The issue changed since it was read"},
    )

    with pytest.raises(IntrospectionAPIError) as raised:
        Issues(fake_api.client()).update(
            ISSUE_ID, IssueUpdate(title="t"), if_match='"1"'
        )
    assert raised.value.status_code == 412
    assert not isinstance(raised.value, ConflictError)


def test_delete_sends_if_match_only_when_given(fake_api: FakeAPI):
    fake_api.add("DELETE", ISSUE_PATH, status=204)
    api = Issues(fake_api.client())

    assert api.delete(ISSUE_ID, if_match='"2026-10-02T11:00:00+00:00"') is None
    assert fake_api.last_request.method == "DELETE"
    assert (
        fake_api.last_request.headers["If-Match"]
        == '"2026-10-02T11:00:00+00:00"'
    )

    api.delete(UUID(ISSUE_ID))
    assert "If-Match" not in fake_api.last_request.headers


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
    fake_api.add(
        "POST", f"{ISSUE_PATH}/comments", status=201, json_body=COMMENT
    )
    fake_api.add("DELETE", ISSUE_PATH, status=204)
    api = AsyncIssues(fake_api.async_client())

    first = await api.list(status=[IssueStatus.OPEN])
    assert first.next == "c2"
    listed = [issue async for issue in api.list(owner=[IssueOwner.ME])]
    assert len(listed) == 2
    assert (await api.get(ISSUE_ID)).title == "Checkout times out"
    created = await api.create(title="t", description="d", task_id=TASK_ID)
    assert created.id == UUID(ISSUE_ID)
    await api.update(ISSUE_ID, IssueUpdate(events=[]), if_match=created.etag)
    comment = await api.comments.create(ISSUE_ID, comment="Ship the retry?")
    assert comment.id == UUID(COMMENT_ID)
    await api.delete(ISSUE_ID, if_match='"k3"')

    calls = [
        (r.method, r.path, r.headers.get("If-Match"))
        for r in fake_api.requests
    ]
    assert calls == [
        ("GET", "/v1/issues", None),
        ("GET", "/v1/issues", None),
        ("GET", "/v1/issues", None),
        ("GET", ISSUE_PATH, None),
        ("POST", "/v1/issues", None),
        ("PATCH", ISSUE_PATH, '"2026-10-02T11:00:00+00:00"'),
        ("POST", f"{ISSUE_PATH}/comments", None),
        ("DELETE", ISSUE_PATH, '"k3"'),
    ]
    assert fake_api.requests[0].params.get_list("status") == ["open"]
    assert fake_api.requests[1].params.get_list("owner") == ["me"]
    assert fake_api.requests[5].json() == {
        "events": [],
    }
    assert fake_api.requests[6].json() == {"comment": "Ship the retry?"}
