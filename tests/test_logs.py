"""Tests for :class:`introspection_sdk.otel.logs.IntrospectionLogs`.

Uses the real in-memory OTLP log exporter (the ``log_exporter``
constructor hook exists precisely for this) — no mocks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

from introspection_sdk.otel.logs import IntrospectionLogs
from introspection_sdk.otel.types import Attr, Baggage, EventName


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


def test_feedback_named_fields_win_over_extra_of_the_same_key(exporter):
    # FeedbackProperties is public, so `extra` can carry a key that collides
    # with a named field. Merging extra last let it replace the feedback name
    # the event was about; every other entry point resolves this
    # the same way.
    from introspection_sdk.otel.types import FeedbackProperties

    props = FeedbackProperties(
        name="thumbs_up",
        comments="great",
        extra={"name": "not the name", "comments": "not the comments", "n": 1},
    )
    assert props.to_dict() == {
        "name": "thumbs_up",
        "comments": "great",
        "n": 1,
    }


def test_identify_sets_user_and_emits(logs, exporter):
    # A bare call emits. While identify() was a
    # context manager this line built a generator and sent nothing.
    logs.identify("user_42", traits={"plan": "pro"})
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[Attr.EVENT_NAME] == EventName.IDENTIFY
    assert attrs[Attr.USER_ID] == "user_42"
    assert attrs[f"{Attr.TRAITS_PREFIX}plan"] == "pro"


def test_identify_does_not_leak_onto_later_events(logs, exporter):
    logs.identify("user_99", anonymous_id="anon_1")
    logs.track("After")
    records = _records(logs, exporter)
    identify_rec = next(
        r
        for r in records
        if r.attributes[Attr.EVENT_NAME] == EventName.IDENTIFY
    )
    assert identify_rec.attributes[Attr.USER_ID] == "user_99"
    assert identify_rec.attributes[Attr.ANONYMOUS_ID] == "anon_1"
    after_rec = next(
        r for r in records if r.attributes[Attr.EVENT_NAME] == "After"
    )
    assert Attr.USER_ID not in after_rec.attributes


def test_set_user_id_scopes_identity_across_events(logs, exporter):
    with logs.set_user_id("user_99"), logs.set_anonymous_id("anon_1"):
        logs.track("Inside")
    (track_rec,) = _records(logs, exporter)
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
    # A non-string baggage value hits the json.dumps() branch in
    # set_baggage and is stored as a string; the emitted event then
    # carries that serialised value.
    vals: dict[str, Any] = {Baggage.CONVERSATION_ID: 123}
    with logs.set_baggage(**vals):
        logs.track("X")
    (record,) = _records(logs, exporter)
    assert record.attributes[Attr.CONVERSATION_ID] == "123"


def test_identify_emits_traits_on_the_record(logs, exporter):
    # The traits argument is what reaches the record; the client keeps no
    # accumulated copy of it.
    logs.identify("u", traits={"a": 1})
    (record,) = _records(logs, exporter)
    assert record.attributes[f"{Attr.TRAITS_PREFIX}a"] == 1
    assert record.attributes[Attr.USER_ID] == "u"


def test_every_record_names_this_sdk_and_its_version_as_the_scope(
    logs, exporter
):
    # The scope rides every record and is how ingest attributes an event to
    # the SDK and release that produced it.
    from introspection_sdk.version import VERSION

    logs.track("E")
    logs.flush()
    (data,) = exporter.get_finished_logs()
    scope = data.instrumentation_scope
    assert scope.name == "introspection-sdk"
    assert scope.version == VERSION

    # The language is deliberately absent from the scope name: it rides the
    # resource, which is where semconv puts it. The scope name's brevity
    # depends on that, so assert it here.
    assert data.resource.attributes["telemetry.sdk.language"] == "python"


def test_shutdown_is_callable(logs):
    logs.shutdown()


def test_missing_token_warns(caplog: pytest.LogCaptureFixture, exporter):
    with caplog.at_level("WARNING", logger="introspection-sdk"):
        IntrospectionLogs(token="", log_exporter=exporter)
    assert "No token provided" in caplog.text


# NOTE: the OTLP endpoint-derivation branch (base_otel_url -> ".../v1/logs")
# in IntrospectionLogs.__init__ is intentionally left uncovered here. The
# only way to exercise it is to build a real OTLPLogExporter, which couples
# the test to real network I/O (the provider flushes on atexit) just to
# verify string concatenation. The right fix is a small source refactor to
# extract a pure `_derive_otlp_endpoint()` helper that can be unit-tested
# directly; that belongs in a change that touches introspection_sdk, not
# this test-only PR.


def test_unserialisable_property_does_not_abort_the_caller(logs, exporter):
    # A telemetry call must never take down the operation it is measuring.
    # A bare json.dumps raised TypeError out of track() on any datetime,
    # set, or bytes in the property dict.
    logs.track("evt", {"when": datetime(2026, 1, 1), "tags": {"a"}})
    (record,) = _records(logs, exporter)
    assert f"{Attr.PROPERTIES_PREFIX}when" in record.attributes
    assert f"{Attr.PROPERTIES_PREFIX}tags" in record.attributes


def test_serialisable_property_still_becomes_json(logs, exporter):
    logs.track("evt", {"meta": {"a": 1}, "n": 5, "ok": True})
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[f"{Attr.PROPERTIES_PREFIX}meta"] == '{"a": 1}'
    assert attrs[f"{Attr.PROPERTIES_PREFIX}n"] == 5
    assert attrs[f"{Attr.PROPERTIES_PREFIX}ok"] is True
