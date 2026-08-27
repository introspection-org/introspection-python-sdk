"""Contract tests for project-level annotations and labels."""

from __future__ import annotations

from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk._errors import NotFoundError, ValidationError
from introspection_sdk.resources.annotations import (
    Annotations,
    AsyncAnnotations,
    ProjectLabels,
)

from .conftest import FakeAPI

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
EVENT_ID = UUID("019fc000-0000-7000-8000-000000000001")


def page(
    records: list[dict[str, object]], next: str | None = None
) -> dict[str, object]:
    return {
        "records": records,
        "count": len(records),
        "total_count": len(records),
        "next": next,
    }


def annotation() -> dict[str, object]:
    return {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "conversation_id": "conversation-1",
        "labels": ["needs-review"],
        "assignee_member_ids": [MEMBER_ID],
        "annotator_member_ids": [],
        "has_comment": False,
        "comment_count": 0,
        "latest_comment": None,
        "latest_comment_member_id": None,
        "updated_at": "2026-08-25T12:00:00Z",
        "updated_by_member_id": MEMBER_ID,
        "assignment_event_id": str(EVENT_ID),
    }


def label() -> dict[str, object]:
    return {
        "slug": "needs-review",
        "color": "#f97316",
        "description": "Expert review queue",
        "created_at": "2026-08-25T12:00:00Z",
        "updated_at": "2026-08-25T12:00:00Z",
    }


def test_list_annotations_forwards_folded_state_filters(
    fake_api: FakeAPI,
) -> None:
    fake_api.add("GET", "/v1/annotations", json_body=page([annotation()]))
    listed = (
        Annotations(fake_api.client(), fake_api.client())
        .list(
            trace_id=TRACE_ID,
            span_id=SPAN_ID,
            label="needs-review",
            assignee_member_id=UUID(MEMBER_ID),
        )
        .page()
    )
    assert listed.records[0].labels == ["needs-review"]
    assert fake_api.last_request.params["trace_id"] == TRACE_ID
    assert fake_api.last_request.params["assignee_member_id"] == MEMBER_ID


def test_list_resolves_email_filters_and_forwards_total(
    fake_api: FakeAPI,
) -> None:
    fake_api.add(
        "GET",
        "/v1/members",
        json_body=page(
            [
                {
                    "id": MEMBER_ID,
                    "email": "expert@example.com",
                    "is_deactivated": False,
                }
            ]
        ),
    )
    fake_api.add("GET", "/v1/annotations", json_body=page([annotation()]))
    listed = (
        Annotations(fake_api.client(), fake_api.client())
        .list(assigned_to_email="expert@example.com", include_total=True)
        .page()
    )
    assert listed.total_count == 1
    assert fake_api.last_request.params["assignee_member_id"] == MEMBER_ID
    assert fake_api.last_request.params["include_total"] == "true"


def test_create_appends_exactly_one_mutation_with_stable_event_id(
    fake_api: FakeAPI,
) -> None:
    fake_api.add("POST", "/v1/annotations", status=204)
    annotations = Annotations(fake_api.client(), fake_api.client())
    annotations.create(
        trace_id=TRACE_ID, span_id=SPAN_ID, labels=[], event_id=EVENT_ID
    )
    assert fake_api.last_request.json() == {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "event_id": str(EVENT_ID),
        "labels": [],
    }
    with pytest.raises(ValidationError):
        annotations.create(
            trace_id=TRACE_ID, span_id=SPAN_ID, labels=[], comment="no"
        )


def test_create_resolves_active_reviewer_emails_across_pages(
    fake_api: FakeAPI,
) -> None:
    fake_api.add_handler(
        "GET",
        "/v1/members",
        lambda request: httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": MEMBER_ID,
                        "email": "Expert@Example.com",
                        "is_deactivated": False,
                    }
                ],
                None,
            ),
        ),
    )
    fake_api.add("POST", "/v1/annotations", status=204)
    Annotations(fake_api.client(), fake_api.client()).create(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        reviewer_emails=[" expert@example.com "],
        event_id=EVENT_ID,
    )
    assert fake_api.requests[0].url.params["member_type"] == "business"
    assert fake_api.last_request.json()["assignee_member_ids"] == [MEMBER_ID]


def test_reviewer_email_must_resolve_uniquely(fake_api: FakeAPI) -> None:
    fake_api.add("GET", "/v1/members", json_body=page([]))
    with pytest.raises(NotFoundError, match="No active domain expert"):
        Annotations(fake_api.client(), fake_api.client()).create(
            trace_id=TRACE_ID,
            span_id=SPAN_ID,
            reviewer_emails=["missing@example.com"],
        )


def test_project_labels_are_validated_and_only_description_updates(
    fake_api: FakeAPI,
) -> None:
    fake_api.add("POST", "/v1/project-labels", json_body=label())
    fake_api.add(
        "PATCH",
        "/v1/project-labels/needs-review",
        json_body={**label(), "description": None},
    )
    labels = ProjectLabels(fake_api.client())
    created = labels.create(
        slug=" needs-review ",
        color="#F97316",
        description="Expert review queue",
    )
    assert created.slug == "needs-review"
    assert fake_api.requests[0].json() == {
        "slug": "needs-review",
        "color": "#f97316",
        "description": "Expert review queue",
    }
    updated = labels.update("needs-review", description=None)
    assert updated.description is None
    assert fake_api.last_request.json() == {"description": None}
    with pytest.raises(PydanticValidationError):
        labels.create(slug="bad", color="orange")


async def test_async_create_comment(fake_api: FakeAPI) -> None:
    fake_api.add("POST", "/v1/annotations", status=204)
    await AsyncAnnotations(
        fake_api.async_client(), fake_api.async_client()
    ).create(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        comment="Explain why this failed",
        event_id=EVENT_ID,
    )
    assert fake_api.last_request.json()["comment"] == "Explain why this failed"


async def test_async_list_resolves_email_only_once_across_pages(
    fake_api: FakeAPI,
) -> None:
    member_calls = 0
    annotation_calls = 0

    def members(request):
        nonlocal member_calls
        member_calls += 1
        return httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": MEMBER_ID,
                        "email": "expert@example.com",
                        "is_deactivated": False,
                    }
                ]
            ),
        )

    def annotations(request):
        nonlocal annotation_calls
        annotation_calls += 1
        cursor = request.url.params.get("next")
        return httpx.Response(
            200,
            json=page([annotation()], "next-page" if cursor is None else None),
        )

    fake_api.add_handler("GET", "/v1/members", members)
    fake_api.add_handler("GET", "/v1/annotations", annotations)
    pager = AsyncAnnotations(
        fake_api.async_client(), fake_api.async_client()
    ).list(annotated_by_email="expert@example.com")
    assert len([record async for record in pager]) == 2
    assert member_calls == 1
    assert annotation_calls == 2
