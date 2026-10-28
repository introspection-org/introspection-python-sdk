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
)
from introspection_sdk.resources.tags import Tags
from introspection_sdk.schemas.tags import (
    AccessTagCreate,
    AnnotationTagCreate,
    TagKind,
    TagUpdate,
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


def label(
    kind: str = "annotation", color: str | None = "#f97316"
) -> dict[str, object]:
    return {
        "kind": kind,
        "name": "needs-review",
        "color": color,
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


def test_annotation_tags_normalize_and_patch_only_what_is_set(
    fake_api: FakeAPI,
) -> None:
    fake_api.add("POST", "/v1/tags", json_body=label())
    fake_api.add(
        "PATCH",
        "/v1/tags/annotation/needs-review",
        json_body={**label(), "description": None},
    )
    tags = Tags(fake_api.client())
    created = tags.create(
        AnnotationTagCreate(
            name=" needs-review ",
            color="#F97316",
            description="Expert review queue",
        )
    )
    assert created.name == "needs-review"
    assert created.kind is TagKind.ANNOTATION
    assert fake_api.requests[0].json() == {
        "kind": "annotation",
        "name": "needs-review",
        "color": "#f97316",
        "description": "Expert review queue",
    }
    updated = tags.update(
        TagKind.ANNOTATION, "needs-review", TagUpdate(description=None)
    )
    assert updated.description is None
    # Only the field that was set: an absent key leaves the value alone.
    assert fake_api.last_request.json() == {"description": None}
    with pytest.raises(PydanticValidationError):
        tags.create(AnnotationTagCreate(name="bad", color="orange"))


def test_an_access_tag_has_no_color_and_encodes_its_opaque_name(
    fake_api: FakeAPI,
) -> None:
    fake_api.add("POST", "/v1/tags", json_body=label("access", None))
    # httpx decodes the path before FakeAPI matches it, so the route is
    # registered decoded; the raw target below is what actually goes on the wire.
    fake_api.add("DELETE", "/v1/tags/access/acme/eu", status=204)
    tags = Tags(fake_api.client())
    created = tags.create(AccessTagCreate(name="acme/eu"))
    assert created.kind is TagKind.ACCESS
    assert created.color is None
    # The kind is the discriminant, and no `color` key is sent at all.
    assert fake_api.requests[0].json() == {"kind": "access", "name": "acme/eu"}
    tags.delete(TagKind.ACCESS, "acme/eu")
    # The opaque name is encoded, so it cannot add a path segment.
    assert b"/v1/tags/access/acme%2Feu" == fake_api.last_request.url.raw_path


def test_a_tag_update_is_refused_locally_when_the_api_would_refuse_it(
    fake_api: FakeAPI,
) -> None:
    tags = Tags(fake_api.client())
    # An access tag has no colour to set.
    with pytest.raises(ValidationError):
        tags.update(TagKind.ACCESS, "acme/eu", TagUpdate(color="#f97316"))
    # An update must name a field.
    with pytest.raises(ValidationError):
        tags.update(TagKind.ANNOTATION, "needs-review", TagUpdate())
    assert fake_api.requests == []


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


FACETS = [
    {"dimension": "label", "value": "needs-review", "count": 2},
    {"dimension": "status", "value": "assigned", "count": 1},
]


def navigation() -> dict[str, object]:
    return {
        "previous": None,
        "current": annotation(),
        "next": None,
        "current_position": 1,
        "total_count": 1,
    }


def test_facets(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/annotations/facets", json_body=FACETS)
    facets = Annotations(fake_api.client(), fake_api.client()).facets()
    assert [(f.dimension, f.count) for f in facets] == [
        ("label", 2),
        ("status", 1),
    ]


def test_navigation_sends_the_target_and_filters(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/annotations/navigation", json_body=navigation())
    window = Annotations(fake_api.client(), fake_api.client()).navigation(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        labels=["needs-review", "flaky"],
        status="assigned",
    )
    assert window.current is not None
    assert window.current.span_id == SPAN_ID
    assert (window.current_position, window.total_count) == (1, 1)
    params = fake_api.last_request.params
    assert (params.get("trace_id"), params.get("span_id")) == (
        TRACE_ID,
        SPAN_ID,
    )
    assert params.get_list("label") == ["needs-review", "flaky"]
    assert params.get("status") == "assigned"
    assert "assignee_member_id" not in params


def test_navigation_of_a_span_the_plane_rejects(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/annotations/navigation",
        status=422,
        json_body={"detail": "trace_id must be 32 hex characters"},
    )
    with pytest.raises(ValidationError):
        Annotations(fake_api.client(), fake_api.client()).navigation(
            trace_id="nope", span_id=SPAN_ID
        )


async def test_async_facets_and_navigation(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/annotations/facets", json_body=[])
    fake_api.add("GET", "/v1/annotations/navigation", json_body=navigation())
    annotations = AsyncAnnotations(
        fake_api.async_client(), fake_api.async_client()
    )
    assert await annotations.facets() == []
    window = await annotations.navigation(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        assignee_member_id=UUID(MEMBER_ID),
    )
    assert window.next is None
    assert fake_api.last_request.params.get("assignee_member_id") == MEMBER_ID
