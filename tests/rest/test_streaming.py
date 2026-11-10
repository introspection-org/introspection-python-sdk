"""Unit tests for AG-UI stream parsing.

Pure function over an iterable of wire lines — no transport, no mocks.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from introspection_sdk._strict_schema import STRICT_SCHEMA_ENV
from introspection_sdk.schemas.agui import (
    EventType,
    ResumeEntry,
    TextMessageContentEvent,
    UnknownEvent,
    validate_ag_ui_event,
)
from introspection_sdk.streaming import parse_ag_ui_events


def test_parse_ag_ui_events_yields_ag_ui_frames_only():
    event = (
        '{"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":"hello"}'
    )
    events = list(
        parse_ag_ui_events(
            [
                "event: heartbeat",
                "data: {}",
                "",
                "event: ag_ui",
                f"data: {event}",
                "",
            ]
        )
    )
    assert len(events) == 1
    assert events[0].type == EventType.TEXT_MESSAGE_CONTENT
    assert events[0].model_dump(exclude_none=True, by_alias=True) == {
        "type": EventType.TEXT_MESSAGE_CONTENT,
        "messageId": "msg-1",
        "delta": "hello",
    }


def test_parse_ag_ui_events_handles_multiline_json():
    events = list(
        parse_ag_ui_events(
            [
                "event: ag_ui",
                'data: {"type":"TEXT_MESSAGE_CONTENT",',
                'data: "messageId":"msg-1",',
                'data: "delta":"hello"}',
                "",
            ]
        )
    )
    assert events[0].model_dump(exclude_none=True, by_alias=True) == {
        "type": "TEXT_MESSAGE_CONTENT",
        "messageId": "msg-1",
        "delta": "hello",
    }


def test_parse_ag_ui_events_rejects_a_frame_that_is_no_event():
    with pytest.raises(ValidationError):
        list(parse_ag_ui_events(["event: ag_ui", 'data: {"type":7}', ""]))


def test_ag_ui_resume_entry_uses_camel_case_aliases():
    entry = ResumeEntry(interrupt_id="interrupt-1", status="resolved")
    assert entry.model_dump(exclude_none=True, by_alias=True) == {
        "interruptId": "interrupt-1",
        "status": "resolved",
    }


def test_ag_ui_run_finished_interrupt_outcome_round_trips():
    event = validate_ag_ui_event(
        {
            "type": "RUN_FINISHED",
            "threadId": "task-1",
            "runId": "run-1",
            "outcome": {
                "type": "interrupt",
                "interrupts": [
                    {
                        "id": "interrupt-1",
                        "reason": "approval",
                        "toolCallId": "tool-1",
                    }
                ],
            },
        }
    )
    dumped = event.model_dump(exclude_none=True, by_alias=True)
    assert dumped["threadId"] == "task-1"
    assert dumped["outcome"]["interrupts"][0]["toolCallId"] == "tool-1"


def test_an_event_type_the_sdk_does_not_model_is_kept_as_unknown():
    events = list(
        parse_ag_ui_events(
            [
                "event: ag_ui",
                'data: {"type":"NEW_EVENT","threadId":"task-1","extra":1}',
                "",
                "event: ag_ui",
                'data: {"type":"RUN_FINISHED","threadId":"task-1","runId":"run-1"}',
                "",
            ]
        )
    )
    assert isinstance(events[0], UnknownEvent)
    assert events[0].model_dump() == {
        "type": "NEW_EVENT",
        "threadId": "task-1",
        "extra": 1,
    }
    assert events[1].type == EventType.RUN_FINISHED


def test_a_known_event_with_a_value_the_sdk_does_not_know_is_kept_as_unknown():
    event = validate_ag_ui_event(
        {
            "type": "MESSAGES_SNAPSHOT",
            "messages": [{"id": "m-1", "role": "narrator", "content": "hi"}],
        }
    )
    assert isinstance(event, UnknownEvent)
    assert event.type == "MESSAGES_SNAPSHOT"


def test_a_known_event_keeps_its_model():
    event = validate_ag_ui_event(
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": "hi"}
    )
    assert isinstance(event, TextMessageContentEvent)


def test_strict_schema_raises_on_an_event_the_sdk_does_not_model(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(STRICT_SCHEMA_ENV, "1")
    with pytest.raises(ValidationError):
        validate_ag_ui_event({"type": "NEW_EVENT"})


def test_a_payload_that_is_no_event_still_raises():
    with pytest.raises(ValidationError):
        validate_ag_ui_event({"delta": "hi"})
