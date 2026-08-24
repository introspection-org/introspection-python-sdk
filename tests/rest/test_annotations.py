"""Contract tests for runner-bound span annotations."""

from __future__ import annotations

from typing import Any

from introspection_sdk.runner_resources.annotations import (
    Annotations,
    AsyncAnnotations,
)
from introspection_sdk.schemas.annotations import Annotation

from .conftest import FakeAPI, paginated

ANNOTATION_ID = "aaaaaaa1-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
DATASET_ID = "ddddddd1-dddd-dddd-dddd-dddddddddddd"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"


def annotation_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ANNOTATION_ID,
        "org_id": "00000000-0000-0000-0000-0000000000aa",
        "project_id": "00000000-0000-0000-0000-0000000000bb",
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "labels": ["hallucination", "tone"],
        "comment": "flagged during review",
        "member_id": MEMBER_ID,
        "completed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(over)
    return payload


def test_annotations_create_sends_only_provided_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/annotations", json_body=annotation_payload())
    annotations = Annotations(fake_api.client())

    created = annotations.create(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        labels=["hallucination", "tone"],
        comment="flagged during review",
    )
    assert created.span_id == SPAN_ID
    assert created.completed_at is not None
    # Omitted optionals (member_id, completed) must not be smuggled
    # onto the wire as nulls — the server's completed default (true)
    # only applies when the field is absent.
    assert fake_api.last_request.json() == {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "labels": ["hallucination", "tone"],
        "comment": "flagged during review",
    }


def test_annotations_create_pending_review_assignment(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/annotations",
        json_body=annotation_payload(labels=[], comment="", completed_at=None),
    )
    created = Annotations(fake_api.client()).create(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        member_id=MEMBER_ID,
        completed=False,
    )
    # A row without completed_at is a pending review.
    assert created.completed_at is None
    # An explicit completed=False must survive the dump — it is what
    # asks for a pending review instead of the server default (true).
    assert fake_api.last_request.json() == {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "member_id": MEMBER_ID,
        "completed": False,
    }


def test_annotations_list_with_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/annotations",
        json_body=paginated([Annotation.model_validate(annotation_payload())]),
    )
    listed = Annotations(fake_api.client()).list(
        member_id=MEMBER_ID,
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        dataset_id=DATASET_ID,
        pending=True,
        label="tone",
    )
    assert str(listed.records[0].member_id) == MEMBER_ID

    params = fake_api.last_request.params
    assert params["member_id"] == MEMBER_ID
    assert params["trace_id"] == TRACE_ID
    assert params["span_id"] == SPAN_ID
    assert params["dataset_id"] == DATASET_ID
    assert params["pending"] == "true"
    assert params["label"] == "tone"
    assert params["include_total"] == "false"


def test_annotations_list_omits_unused_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/annotations",
        json_body=paginated([]),
    )
    Annotations(fake_api.client()).list().page()
    params = fake_api.last_request.params
    for name in (
        "member_id",
        "trace_id",
        "span_id",
        "dataset_id",
        "pending",
        "label",
    ):
        assert name not in params


def test_annotations_get(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/annotations/{ANNOTATION_ID}",
        json_body=annotation_payload(),
    )
    got = Annotations(fake_api.client()).get(ANNOTATION_ID)
    assert str(got.id) == ANNOTATION_ID


def test_annotations_update_omits_untouched_labels(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/annotations/{ANNOTATION_ID}",
        json_body=annotation_payload(),
    )
    Annotations(fake_api.client()).update(
        ANNOTATION_ID,
        comment="updated",
        completed=True,
    )
    # Labels omitted -> not in the body, so the server leaves them alone.
    assert fake_api.last_request.json() == {
        "comment": "updated",
        "completed": True,
    }


def test_annotations_update_explicit_empty_labels_clears(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/annotations/{ANNOTATION_ID}",
        json_body=annotation_payload(labels=[]),
    )
    Annotations(fake_api.client()).update(ANNOTATION_ID, labels=[])
    # An explicit [] replaces wholesale (clears); it must survive the
    # dump rather than being dropped like an omitted list.
    assert fake_api.last_request.json() == {"labels": []}


def test_annotations_delete(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/annotations/{ANNOTATION_ID}", status=204)
    Annotations(fake_api.client()).delete(ANNOTATION_ID)
    assert fake_api.last_request.method == "DELETE"
    assert fake_api.last_request.path == f"/v1/annotations/{ANNOTATION_ID}"


async def test_async_annotations_create_and_update(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/annotations", json_body=annotation_payload())
    fake_api.add(
        "PATCH",
        f"/v1/annotations/{ANNOTATION_ID}",
        json_body=annotation_payload(completed_at=None),
    )
    annotations = AsyncAnnotations(fake_api.async_client())

    created = await annotations.create(
        trace_id=TRACE_ID,
        span_id=SPAN_ID,
        labels=["tone"],
    )
    assert created.trace_id == TRACE_ID
    assert fake_api.last_request.json() == {
        "trace_id": TRACE_ID,
        "span_id": SPAN_ID,
        "labels": ["tone"],
    }

    updated = await annotations.update(ANNOTATION_ID, completed=False)
    assert updated.completed_at is None
    assert fake_api.last_request.json() == {"completed": False}
