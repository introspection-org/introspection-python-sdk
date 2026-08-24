"""Contract tests for runner-bound expert-distillation annotations."""

from __future__ import annotations

from typing import Any

from introspection_sdk.runner_resources.annotations import (
    Annotations,
    AsyncAnnotations,
)
from introspection_sdk.schemas.annotations import (
    Annotation,
    AnnotationKind,
)

from .conftest import FakeAPI, paginated

ANNOTATION_ID = "aaaaaaa1-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
DATASET_ID = "ddddddd1-dddd-dddd-dddd-dddddddddddd"
CONVERSATION_ID = "conv-1"


def annotation_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ANNOTATION_ID,
        "org_id": "00000000-0000-0000-0000-0000000000aa",
        "project_id": "00000000-0000-0000-0000-0000000000bb",
        "conversation_id": CONVERSATION_ID,
        "kind": "mark",
        "parent_id": None,
        "selection": {
            "message_id": "msg-1",
            "start": 3,
            "end": 17,
            "quoted_text": "the quoted span",
        },
        "labels": ["tone", "hallucination"],
        "comment": "flagged during review",
        "member_id": MEMBER_ID,
        "actor_member_id": None,
        "actor_type": None,
        "share_id": None,
        "dataset_id": DATASET_ID,
        "completed_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    payload.update(over)
    return payload


def test_annotations_create_sends_only_provided_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/annotations", json_body=annotation_payload())
    annotations = Annotations(fake_api.client())

    created = annotations.create(
        conversation_id=CONVERSATION_ID,
        kind="mark",
        selection={
            "message_id": "msg-1",
            "start": 3,
            "end": 17,
            "quoted_text": "the quoted span",
        },
        labels=["tone", "hallucination"],
        comment="flagged during review",
        dataset_id=DATASET_ID,
    )
    assert created.kind is AnnotationKind.MARK
    assert created.selection is not None
    assert created.selection.quoted_text == "the quoted span"
    # Omitted optionals (member_id, parent_id) must not be smuggled onto
    # the wire as nulls; the selection's omitted anchors stay off too.
    assert fake_api.last_request.json() == {
        "conversation_id": CONVERSATION_ID,
        "kind": "mark",
        "selection": {
            "message_id": "msg-1",
            "start": 3,
            "end": 17,
            "quoted_text": "the quoted span",
        },
        "labels": ["tone", "hallucination"],
        "comment": "flagged during review",
        "dataset_id": DATASET_ID,
    }


def test_annotations_create_review_assignee(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/annotations",
        json_body=annotation_payload(kind="review", member_id=MEMBER_ID),
    )
    Annotations(fake_api.client()).create(
        conversation_id=CONVERSATION_ID,
        kind=AnnotationKind.REVIEW,
        member_id=MEMBER_ID,
    )
    assert fake_api.last_request.json() == {
        "conversation_id": CONVERSATION_ID,
        "kind": "review",
        "member_id": MEMBER_ID,
    }


def test_annotations_list_with_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/annotations",
        json_body=paginated([Annotation.model_validate(annotation_payload())]),
    )
    listed = Annotations(fake_api.client()).list(
        kind="review",
        member_id=MEMBER_ID,
        conversation_id=CONVERSATION_ID,
        dataset_id=DATASET_ID,
        pending=True,
        label="tone",
    )
    assert str(listed.records[0].member_id) == MEMBER_ID

    params = fake_api.last_request.params
    assert params["kind"] == "review"
    assert params["member_id"] == MEMBER_ID
    assert params["conversation_id"] == CONVERSATION_ID
    assert params["dataset_id"] == DATASET_ID
    assert params["pending"] == "true"
    assert params["label"] == "tone"
    assert params["include_total"] == "false"
    # Unused filters stay off the wire entirely.
    assert "parent_id" not in params


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
        json_body=annotation_payload(completed_at="2026-01-02T00:00:00Z"),
    )
    annotations = AsyncAnnotations(fake_api.async_client())

    created = await annotations.create(
        conversation_id=CONVERSATION_ID,
        kind="membership",
        dataset_id=DATASET_ID,
    )
    assert str(created.dataset_id) == DATASET_ID
    assert fake_api.last_request.json() == {
        "conversation_id": CONVERSATION_ID,
        "kind": "membership",
        "dataset_id": DATASET_ID,
    }

    updated = await annotations.update(ANNOTATION_ID, completed=True)
    assert updated.completed_at is not None
    assert fake_api.last_request.json() == {"completed": True}
