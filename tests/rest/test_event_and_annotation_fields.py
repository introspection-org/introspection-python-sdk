"""Strict decoding of the annotation state and the annotation, feedback and
judgement event payloads, in the shape the Data Plane API returns them."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from introspection_sdk._strict_schema import STRICT_SCHEMA_ENV
from introspection_sdk.resources.annotations import Annotations
from introspection_sdk.runner_resources.events import Events
from introspection_sdk.schemas.events import (
    AnnotationEvent,
    FeedbackEvent,
    IntrospectionEventName,
    JudgementEvent,
    JudgementResultSchema,
    JudgeType,
)

from .conftest import FakeAPI

MEMBER_ID = "00000000-0000-0000-0000-0000000000cc"
AGENT_ID = "00000000-0000-0000-0000-0000000000dd"


@pytest.fixture(autouse=True)
def strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STRICT_SCHEMA_ENV, "1")


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


def test_annotation_state_models_the_comment_actor_fields(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/annotations",
        json_body=page(
            [
                {
                    "trace_id": "0af7651916cd43dd8448eb211c80319c",
                    "span_id": "b7ad6b7169203331",
                    "conversation_id": "conversation-1",
                    "labels": ["walk"],
                    "assignee_member_ids": [],
                    "annotator_member_ids": [MEMBER_ID],
                    "has_comment": True,
                    "comment_count": 1,
                    "latest_comment": "looks right",
                    "latest_comment_member_id": MEMBER_ID,
                    "commenter_member_ids": [MEMBER_ID, AGENT_ID],
                    "human_commenter_member_ids": [MEMBER_ID],
                    "has_human_comment": True,
                    "latest_comment_actor_member_id": AGENT_ID,
                    "latest_comment_actor_type": "agent",
                    "updated_at": "2026-11-10T05:00:00Z",
                    "updated_by_member_id": MEMBER_ID,
                    "assignment_event_id": None,
                }
            ]
        ),
    )

    (state,) = (
        Annotations(fake_api.client(), fake_api.client()).list().page().records
    )

    assert state.commenter_member_ids == [UUID(MEMBER_ID), UUID(AGENT_ID)]
    assert state.human_commenter_member_ids == [UUID(MEMBER_ID)]
    assert state.has_human_comment is True
    assert state.latest_comment_actor_member_id == UUID(AGENT_ID)
    assert state.latest_comment_actor_type == "agent"


def test_judgement_payload_models_every_field(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/events",
        json_body=page(
            [
                event(
                    "introspection.judgement",
                    {
                        "judgement_id": "judgement-1",
                        "judge_id": "judge-1",
                        "judge_slug": "helpful",
                        "judge_type": "online",
                        "result": "pass",
                        "result_schema": "question_scores.v1",
                        "runtime_slug": "hello-mcp",
                        "status": "completed",
                        "error_class": None,
                        "error_message": None,
                        "source_component": "judge-engine",
                        "reasoning": "answers the question",
                        "reason": None,
                        "definition_hash": "d1",
                        "engine_version": "1.2.3",
                        "judge_provider": "anthropic",
                        "judge_model": "claude",
                        "contract_version": "1",
                        "sequence_hash": "s1",
                        "experiment_arm_id": None,
                        "input_tokens": 120,
                        "output_tokens": 30,
                        "total_tokens": 150,
                        "scores": {"q1": 1},
                        "questions": {"q1": "Is it helpful?"},
                        "policy_id": None,
                        "policy_action": None,
                        "request_host": None,
                        "request_method": None,
                        "request_path": None,
                    },
                ),
                event(
                    "introspection.judgement",
                    {
                        "judgement_id": "judgement-2",
                        "judge_type": "batch",
                        "result_schema": "verdict.v2",
                    },
                ),
            ]
        ),
    )

    first, second = Events(fake_api.client()).list(
        IntrospectionEventName.JUDGEMENT
    )

    assert isinstance(first, JudgementEvent)
    judgement = first.payload
    assert judgement.judge_slug == "helpful"
    assert judgement.judge_type is JudgeType.ONLINE
    assert judgement.result_schema is JudgementResultSchema.QUESTION_SCORES_V1
    assert judgement.status == "completed"
    assert judgement.engine_version == "1.2.3"
    assert judgement.total_tokens == 150
    assert judgement.scores == {"q1": 1}
    assert judgement.questions == {"q1": "Is it helpful?"}
    # A value the API adds later still decodes, as a plain string.
    assert isinstance(second, JudgementEvent)
    assert second.payload.judge_type == "batch"
    assert second.payload.result_schema == "verdict.v2"


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
