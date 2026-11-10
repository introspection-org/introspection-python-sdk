"""The annotation, feedback, judgement and issue event payloads, in the shape
the Data Plane API returns them."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk.runner_resources.events import Events
from introspection_sdk.schemas.events import (
    AnnotationEvent,
    FeedbackEvent,
    IntrospectionEventName,
    IssueActivityEvent,
    IssueCommentedPayload,
    IssueCreatedPayload,
    IssueDeletedPayload,
    IssueEventAction,
    IssueUpdatedPayload,
    JudgementEgressPayload,
    JudgementEvent,
    JudgementVerdictPayload,
    JudgeType,
    UnknownIssuePayload,
    UnknownJudgementPayload,
)

from .conftest import FakeAPI

MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
AGENT_ID = "00000000-0000-0000-0000-0000000000dd"

SHARED: dict[str, Any] = {
    "judgement_id": "judgement-1",
    "judge_id": "judge-1",
    "judge_slug": "helpful",
    "judge_type": "online",
    "runtime_slug": "hello-mcp",
    "result": "pass",
    "status": "ok",
    "error_class": None,
    "error_message": None,
    "source_component": "introspection-judge",
    "judge_model": "grader-1",
    "experiment_arm_id": None,
}
VERDICT: dict[str, Any] = {
    **SHARED,
    "kind": "verdict",
    "reasoning": "answers the question",
    "definition_hash": "d1",
    "engine_version": "1.2.3",
    "judge_provider": "provider",
    "contract_version": "1",
    "sequence_hash": "s1",
    "input_tokens": 120,
    "output_tokens": 30,
    "total_tokens": 150,
}
EGRESS: dict[str, Any] = {
    **SHARED,
    "kind": "egress",
    "source_component": "egress",
    "result": "deny",
    "scores": {"exfiltration": 92},
    "questions": {"exfiltration": "Does the request leak data?"},
    "policy_id": "no-exfiltration",
    "policy_action": "http.request",
    "reason": "The request posts a secret.",
    "request_host": "example.com",
    "request_method": "POST",
    "request_path": "/upload",
}


def page(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"records": records, "count": len(records), "next": None}


def event(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "0199a1b2-0000-5000-8000-000000000001",
        "timestamp": "2026-11-10T05:00:00Z",
        "event_name": event_name,
        "conversation_id": "conversation-1",
        "payload": payload,
    }


def judgements(fake_api: FakeAPI, *payloads: dict[str, Any]) -> list[Any]:
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=page(
            [event("introspection.judgement", payload) for payload in payloads]
        ),
    )
    records = list(Events(fake_api.client()).list("introspection.judgement"))
    assert all(isinstance(record, JudgementEvent) for record in records)
    return [record.payload for record in records]


def test_judgement_payload_is_a_union_on_kind(fake_api: FakeAPI):
    verdict, egress = judgements(fake_api, VERDICT, EGRESS)

    assert isinstance(verdict, JudgementVerdictPayload)
    assert verdict.kind == "verdict"
    assert verdict.judge_type is JudgeType.ONLINE
    assert (verdict.judge_slug, verdict.status) == ("helpful", "ok")
    assert (verdict.engine_version, verdict.total_tokens) == ("1.2.3", 150)
    assert isinstance(egress, JudgementEgressPayload)
    assert egress.kind == "egress"
    assert egress.scores == {"exfiltration": 92}
    assert egress.questions == {"exfiltration": "Does the request leak data?"}
    assert (egress.policy_id, egress.request_method) == (
        "no-exfiltration",
        "POST",
    )


def test_a_judgement_without_kind_does_not_decode(fake_api: FakeAPI):
    with pytest.raises(PydanticValidationError):
        judgements(fake_api, {"judgement_id": "judgement-2"})


def test_an_unknown_judgement_kind_keeps_the_row(fake_api: FakeAPI):
    unknown, verdict = judgements(
        fake_api,
        {**SHARED, "kind": "consensus", "judge_type": "batch", "votes": 3},
        VERDICT,
    )

    assert isinstance(unknown, UnknownJudgementPayload)
    assert (unknown.kind, unknown.judge_slug) == ("consensus", "helpful")
    # An enum value the API adds later stays a plain string.
    assert unknown.judge_type == "batch"
    assert unknown.model_extra == {"votes": 3}
    assert isinstance(verdict, JudgementVerdictPayload)
    # The decoded payload validates again, as itself.
    again = JudgementEvent.model_validate(
        event("introspection.judgement", unknown.model_dump(mode="json"))
    )
    assert isinstance(again.payload, UnknownJudgementPayload)
    assert (
        JudgementEvent(
            **{**event("introspection.judgement", {}), "payload": verdict}
        ).payload
        is verdict
    )


def test_annotation_payload_models_its_actor(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=page(
            [
                event(
                    "introspection.annotation",
                    {
                        "member_id": MEMBER_ID,
                        "actor_member_id": AGENT_ID,
                        "actor_member_type": "agent",
                        "labels": ["walk"],
                        "comment": None,
                        "assignee_member_ids": None,
                    },
                )
            ]
        ),
    )

    (annotation,) = Events(fake_api.client()).list(
        IntrospectionEventName.ANNOTATION
    )

    assert isinstance(annotation, AnnotationEvent)
    assert annotation.payload.actor_member_id == UUID(AGENT_ID)
    assert annotation.payload.actor_member_type == "agent"


def test_feedback_payload_models_its_author(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=page(
            [
                event(
                    "introspection.feedback",
                    {
                        "name": "thumbs",
                        "value": 1.0,
                        "author_member_id": MEMBER_ID,
                    },
                )
            ]
        ),
    )

    (feedback,) = Events(fake_api.client()).list(
        IntrospectionEventName.FEEDBACK
    )

    assert isinstance(feedback, FeedbackEvent)
    assert feedback.payload.author_member_id == UUID(MEMBER_ID)


ISSUE_ID = "019fc000-0000-7000-8000-0000000000a1"
# The events read drops nulls, so an unset field is an absent key.
ISSUE_SHARED: dict[str, Any] = {
    "issue_id": ISSUE_ID,
    "revision": 2,
    "member_id": MEMBER_ID,
}


def issue_payloads(fake_api: FakeAPI, *payloads: dict[str, Any]) -> list[Any]:
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=page(
            [
                event("introspection.issue", {**ISSUE_SHARED, **payload})
                for payload in payloads
            ]
        ),
    )
    records = list(
        Events(fake_api.client()).list(
            IntrospectionEventName.ISSUE, issue_id=ISSUE_ID
        )
    )
    params = fake_api.last_request.params
    assert params["event_name"] == "introspection.issue"
    assert params["issue_id"] == ISSUE_ID
    assert all(isinstance(record, IssueActivityEvent) for record in records)
    return [record.payload for record in records]


def test_issue_created_carries_its_data(fake_api: FakeAPI):
    (created,) = issue_payloads(
        fake_api,
        {
            "action": "created",
            "data": {"title": "Flaky export", "priority": "high"},
        },
    )

    assert isinstance(created, IssueCreatedPayload)
    assert created.action is IssueEventAction.CREATED
    assert (created.issue_id, created.revision) == (UUID(ISSUE_ID), 2)
    assert created.member_id == UUID(MEMBER_ID)
    assert (created.actor_member_id, created.actor_member_type) == (None, None)
    assert created.data == {"title": "Flaky export", "priority": "high"}
    assert created.model_extra == {}


def test_issue_updated_carries_its_changes(fake_api: FakeAPI):
    (updated,) = issue_payloads(
        fake_api,
        {
            "action": "updated",
            "actor_member_id": AGENT_ID,
            "actor_member_type": "agent",
            "changes": {
                "status": {"before": "open", "after": "waiting"},
                # A side that was empty is dropped with the other nulls.
                "assignee_member_id": {"after": MEMBER_ID},
            },
        },
    )

    assert isinstance(updated, IssueUpdatedPayload)
    assert (updated.actor_member_id, updated.actor_member_type) == (
        UUID(AGENT_ID),
        "agent",
    )
    assert updated.changes["status"].before == "open"
    assert updated.changes["status"].after == "waiting"
    assert updated.changes["assignee_member_id"].before is None
    assert updated.changes["assignee_member_id"].after == MEMBER_ID


def test_issue_commented_carries_the_comment(fake_api: FakeAPI):
    (commented,) = issue_payloads(
        fake_api, {"action": "commented", "comment": "Ship the retry?"}
    )

    assert isinstance(commented, IssueCommentedPayload)
    assert commented.action is IssueEventAction.COMMENTED
    assert (commented.comment, commented.member_id) == (
        "Ship the retry?",
        UUID(MEMBER_ID),
    )


def test_issue_deleted_carries_only_the_shared_fields(fake_api: FakeAPI):
    (deleted,) = issue_payloads(fake_api, {"action": "deleted"})

    assert isinstance(deleted, IssueDeletedPayload)
    assert deleted.issue_id == UUID(ISSUE_ID)
    assert deleted.model_extra == {}


def test_an_issue_member_missing_its_own_field_does_not_decode(
    fake_api: FakeAPI,
):
    with pytest.raises(PydanticValidationError):
        issue_payloads(fake_api, {"action": "commented"})


def test_an_unknown_issue_action_keeps_the_row(fake_api: FakeAPI):
    unknown, deleted = issue_payloads(
        fake_api,
        {"action": "request.created", "request": {"question": "q"}},
        {"action": "deleted"},
    )

    assert isinstance(unknown, UnknownIssuePayload)
    assert (unknown.action, unknown.member_id) == (
        "request.created",
        UUID(MEMBER_ID),
    )
    assert unknown.model_extra == {"request": {"question": "q"}}
    assert isinstance(deleted, IssueDeletedPayload)
