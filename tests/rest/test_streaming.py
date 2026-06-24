"""Unit tests for AG-UI stream parsing.

Pure function over an iterable of wire lines — no transport, no mocks.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from introspection_sdk.schemas.agui import (
    EventType,
    ResumeEntry,
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


def test_parse_ag_ui_events_rejects_invalid_payload():
    with pytest.raises(ValidationError):
        list(parse_ag_ui_events(["event: ag_ui", 'data: {"type":"NOPE"}', ""]))


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
