"""Unit tests for the SSE parser (:func:`parse_sse`).

Pure function over an iterable of wire lines — no transport, no mocks.
"""

from __future__ import annotations

from introspection_sdk.streaming import SseEvent, parse_sse


def _events(lines: list[str]) -> list[SseEvent]:
    return list(parse_sse(lines))


def test_single_event_with_event_and_data():
    events = _events(["event: text", "data: hello", ""])
    assert len(events) == 1
    assert events[0].event == "text"
    assert events[0].data == "hello"


def test_default_event_name_is_message():
    events = _events(["data: hi", ""])
    assert events[0].event == "message"
    assert events[0].data == "hi"


def test_multiline_data_is_joined_with_newlines():
    events = _events(["data: line1", "data: line2", ""])
    assert events[0].data == "line1\nline2"


def test_comment_lines_are_ignored():
    events = _events([": keep-alive", "data: payload", ""])
    assert len(events) == 1
    assert events[0].data == "payload"


def test_id_and_retry_fields_are_parsed():
    events = _events(["id: 7", "retry: 3000", "data: x", ""])
    assert events[0].id == "7"
    assert events[0].retry == 3000


def test_invalid_retry_is_ignored():
    events = _events(["retry: soon", "data: x", ""])
    assert events[0].retry is None


def test_leading_space_after_colon_is_stripped_once():
    # "data:  x" -> value is " x" (only the first space is consumed).
    events = _events(["data:  x", ""])
    assert events[0].data == " x"


def test_value_without_space_is_preserved():
    events = _events(["data:x", ""])
    assert events[0].data == "x"


def test_multiple_events_separated_by_blank_lines():
    events = _events(["data: a", "", "data: b", "", "data: c", ""])
    assert [e.data for e in events] == ["a", "b", "c"]


def test_blank_lines_without_content_emit_nothing():
    assert _events(["", "", ""]) == []


def test_trailing_event_without_blank_line_is_flushed():
    events = _events(["event: done", "data: bye"])
    assert len(events) == 1
    assert events[0].event == "done"
    assert events[0].data == "bye"


def test_event_only_frame_has_empty_data():
    events = _events(["event: ping", ""])
    assert events[0].event == "ping"
    assert events[0].data == ""
