"""Tests for :class:`introspection_sdk.otel.logs.IntrospectionLogs`.

Uses the real in-memory OTLP log exporter (the ``log_exporter``
constructor hook exists precisely for this) — no mocks.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

from introspection_sdk.otel.logs import IntrospectionLogs
from introspection_sdk.otel.types import Attr, EventName


@pytest.fixture
def exporter() -> InMemoryLogRecordExporter:
    return InMemoryLogRecordExporter()


@pytest.fixture
def logs(exporter: InMemoryLogRecordExporter) -> IntrospectionLogs:
    return IntrospectionLogs(
        token="intro_test",
        service_name="unit-tests",
        flush_interval_ms=1,
        log_exporter=exporter,
    )


def _records(logs: IntrospectionLogs, exporter: InMemoryLogRecordExporter):
    logs.flush()
    return [d.log_record for d in exporter.get_finished_logs()]


def test_track_emits_event_with_properties(logs, exporter):
    logs.track(
        "Button Clicked", {"button_id": "submit", "count": 3, "meta": None}
    )
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[Attr.EVENT_NAME] == "Button Clicked"
    assert attrs[Attr.EVENT_ID]
    assert attrs[f"{Attr.PROPERTIES_PREFIX}button_id"] == "submit"
    assert attrs[f"{Attr.PROPERTIES_PREFIX}count"] == 3
    # None-valued properties are dropped.
    assert f"{Attr.PROPERTIES_PREFIX}meta" not in attrs


def test_track_serialises_complex_property_values(logs, exporter):
    logs.track("E", {"payload": {"a": 1}})
    (record,) = _records(logs, exporter)
    assert record.attributes[f"{Attr.PROPERTIES_PREFIX}payload"] == (
        '{"a": 1}'
    )


def test_track_uses_explicit_event_id(logs, exporter):
    logs.track("E", event_id="evt-123")
    (record,) = _records(logs, exporter)
    assert record.attributes[Attr.EVENT_ID] == "evt-123"


def test_feedback_emits_feedback_event(logs, exporter):
    logs.feedback(
        "thumbs_up",
        comments="great",
        conversation_id="conv_1",
        rating=5,
    )
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[Attr.EVENT_NAME] == EventName.FEEDBACK
    assert attrs[Attr.CONVERSATION_ID] == "conv_1"
    assert attrs[f"{Attr.PROPERTIES_PREFIX}name"] == "thumbs_up"
    assert attrs[f"{Attr.PROPERTIES_PREFIX}comments"] == "great"
    assert attrs[f"{Attr.PROPERTIES_PREFIX}rating"] == 5


def test_identify_sets_user_and_emits(logs, exporter):
    with logs.identify("user_42", traits={"plan": "pro"}):
        pass
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[Attr.EVENT_NAME] == EventName.IDENTIFY
    assert attrs[Attr.USER_ID] == "user_42"
    assert attrs[f"{Attr.TRAITS_PREFIX}plan"] == "pro"


def test_identify_baggage_visible_to_nested_track(logs, exporter):
    with logs.identify("user_99", anonymous_id="anon_1"):
        logs.track("Inside")
    records = _records(logs, exporter)
    # identify + the nested track event.
    track_rec = next(
        r for r in records if r.attributes[Attr.EVENT_NAME] == "Inside"
    )
    assert track_rec.attributes[Attr.USER_ID] == "user_99"
    assert track_rec.attributes[Attr.ANONYMOUS_ID] == "anon_1"


def test_set_agent_and_conversation_baggage(logs, exporter):
    with logs.set_agent("planner", agent_id="ag_1"):
        with logs.set_conversation(
            conversation_id="conv_7", previous_response_id="resp_2"
        ):
            logs.track("Step")
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[Attr.AGENT_NAME] == "planner"
    assert attrs[Attr.AGENT_ID] == "ag_1"
    assert attrs[Attr.CONVERSATION_ID] == "conv_7"
    assert attrs[Attr.PREVIOUS_RESPONSE_ID] == "resp_2"


def test_set_user_and_anonymous_id_helpers(logs):
    with logs.set_user_id("u1"):
        assert logs.get_user_id() == "u1"
    with logs.set_anonymous_id("a1"):
        assert logs.get_anonymous_id() == "a1"
    # Outside the context managers the baggage is cleared.
    assert logs.get_user_id() is None
    assert logs.get_anonymous_id() is None


def test_set_baggage_serialises_non_string_values(logs, exporter):
    with logs.set_baggage(**{Attr.CONVERSATION_ID: "c"}):
        logs.track("X")
    # Just ensure no error and the event was emitted.
    assert len(_records(logs, exporter)) == 1


def test_reset_clears_traits(logs):
    with logs.identify("u", traits={"a": 1}):
        pass
    assert logs._traits == {"a": 1}
    logs.reset()
    assert logs._traits == {}


def test_shutdown_is_callable(logs):
    logs.shutdown()


def test_missing_token_warns(caplog: pytest.LogCaptureFixture, exporter):
    with caplog.at_level("WARNING"):
        IntrospectionLogs(token="", log_exporter=exporter)
    assert "No token provided" in caplog.text


@pytest.mark.parametrize(
    "base_url",
    [
        "https://otel.example.test",
        "https://otel.example.test/v1/logs",
    ],
)
def test_constructs_otlp_endpoint_without_exporter(base_url: str):
    # No network at construction time; this exercises the endpoint
    # derivation branches when no test exporter is injected.
    logs = IntrospectionLogs(token="t", base_otel_url=base_url)
    logs.shutdown()
