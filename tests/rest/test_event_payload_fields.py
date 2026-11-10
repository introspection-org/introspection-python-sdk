"""The annotation, feedback and judgement event payloads, in the shape the
Data Plane API returns them."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from introspection_sdk.runner_resources.events import Events
from introspection_sdk.schemas.events import (
    AnnotationEvent,
    FeedbackEvent,
    IntrospectionEventName,
    JudgementEgressPayload,
    JudgementEvent,
    JudgementVerdictPayload,
    JudgeType,
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


def test_a_judgement_without_kind_is_told_apart_by_result_schema(
    fake_api: FakeAPI,
):
    """A data plane that predates ``kind`` sends one flat payload."""
    flat = {
        key: value
        for key, value in {**EGRESS, **VERDICT}.items()
        if key != "kind"
    }
    verdict, egress, bare = judgements(
        fake_api,
        {**flat, "result_schema": "verdict.v1"},
        {**flat, "result_schema": "question_scores.v1"},
        {"judgement_id": "judgement-2"},
    )

    assert isinstance(verdict, JudgementVerdictPayload)
    assert (verdict.kind, verdict.reasoning) == (
        "verdict",
        VERDICT["reasoning"],
    )
    assert isinstance(egress, JudgementEgressPayload)
    assert (egress.kind, egress.scores) == ("egress", EGRESS["scores"])
    assert isinstance(bare, JudgementVerdictPayload)


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
