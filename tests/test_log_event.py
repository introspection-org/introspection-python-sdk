"""``log_event`` — the custom-event primitive ``track`` delegates to — on
:class:`IntrospectionLogs` and the module-level ``init()`` proxy.

OTel-only: records go to the in-memory log exporter through the
``log_exporter`` seam, nothing crosses a network boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

import introspection_sdk.otel as introspection
from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel import _reset_for_tests
from introspection_sdk.otel.logs import IntrospectionLogs
from introspection_sdk.otel.types import (
    RESERVED_EVENT_NAME_PREFIXES,
    Attr,
    EventIdentity,
)
from introspection_sdk.testing import TestSpanExporter


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


def test_emits_custom_name_with_attributes_under_properties(logs, exporter):
    logs.log_event(
        "ark.feed.entry",
        {"entry_id": "e_1", "score": 0.9, "tags": ["a", "b"], "skipped": None},
    )
    (record,) = _records(logs, exporter)
    attrs = record.attributes
    assert attrs[Attr.EVENT_NAME] == "ark.feed.entry"
    assert attrs["properties.entry_id"] == "e_1"
    assert attrs["properties.score"] == 0.9
    assert attrs["properties.tags"] == '["a","b"]'
    assert "properties.skipped" not in attrs
    assert attrs[Attr.EVENT_ID].startswith("intro_event_")
    assert record.severity_number == SeverityNumber.INFO
    assert record.severity_text == "INFO"


def test_passes_caller_supplied_event_id_through_for_dedup(logs, exporter):
    logs.log_event(
        "ark.feed.entry", {"entry_id": "e_1"}, event_id="feed-entry:e_1"
    )
    logs.log_event(
        "ark.feed.entry", {"entry_id": "e_1"}, event_id="feed-entry:e_1"
    )
    records = _records(logs, exporter)
    assert [r.attributes[Attr.EVENT_ID] for r in records] == [
        "feed-entry:e_1",
        "feed-entry:e_1",
    ]


def test_honours_datetime_timestamp_and_severity(logs, exporter):
    at = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
    logs.log_event("ark.sync.failed", timestamp=at, severity="ERROR")
    (record,) = _records(logs, exporter)
    assert record.timestamp == 1767323045_678_000_000
    assert record.severity_number == SeverityNumber.ERROR
    assert record.severity_text == "ERROR"


def test_accepts_epoch_milliseconds_timestamp(logs, exporter):
    logs.log_event("ark.a", timestamp=1767323045678, severity="DEBUG")
    logs.log_event("ark.b", severity="WARN")
    a, b = _records(logs, exporter)
    assert a.timestamp == 1767323045_678_000_000
    assert a.severity_number == SeverityNumber.DEBUG
    assert b.severity_number == SeverityNumber.WARN
    assert b.severity_text == "WARN"


def test_rejects_unknown_severity(logs, exporter):
    with pytest.raises(ValueError, match="severity"):
        logs.log_event("ark.a", severity="FATAL")
    assert _records(logs, exporter) == []


def test_identity_overrides_the_context_field_by_field(logs, exporter):
    with logs.set_user_id("ctx_user"):
        logs.log_event(
            "ark.a",
            identity=EventIdentity(
                user_id="explicit_user", anonymous_id="anon_1"
            ),
        )
        logs.log_event("ark.b", identity=EventIdentity(anonymous_id="anon_2"))
    a, b = _records(logs, exporter)
    assert a.attributes[Attr.USER_ID] == "explicit_user"
    assert a.attributes[Attr.ANONYMOUS_ID] == "anon_1"
    # An omitted field still falls back to the scoped identity.
    assert b.attributes[Attr.USER_ID] == "ctx_user"
    assert b.attributes[Attr.ANONYMOUS_ID] == "anon_2"


@pytest.mark.parametrize(
    "name",
    [
        "introspection.track",
        "introspection.feedback",
        "gen_ai.client.inference",
    ],
)
def test_rejects_reserved_names(logs, exporter, name):
    with pytest.raises(ValueError, match="reserved"):
        logs.log_event(name)
    assert _records(logs, exporter) == []


def test_rejects_empty_name(logs):
    with pytest.raises(ValueError, match="non-empty"):
        logs.log_event("")


def test_allows_names_that_merely_contain_a_reserved_word(logs, exporter):
    logs.log_event("my.introspection.event")
    logs.log_event("gen_ai_usage")
    assert len(_records(logs, exporter)) == 2


def test_track_delegates_to_log_event(logs, exporter):
    calls: list[tuple[tuple, dict]] = []
    original = logs.log_event

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        original(*args, **kwargs)

    logs.log_event = spy
    logs.track("Button Clicked", {"buttonId": "submit"}, event_id="e1")
    assert calls == [
        (("Button Clicked", {"buttonId": "submit"}), {"event_id": "e1"})
    ]
    (record,) = _records(logs, exporter)
    assert record.attributes[Attr.EVENT_NAME] == "Button Clicked"
    assert record.attributes[Attr.EVENT_ID] == "e1"
    assert record.attributes["properties.buttonId"] == "submit"


def test_track_rejects_reserved_names_too(logs):
    with pytest.raises(ValueError, match="reserved"):
        logs.track("introspection.track")


# --- module-level proxy ------------------------------------------------


def setup_function():
    _reset_for_tests()


def teardown_function():
    _reset_for_tests()


def test_names_the_reserved_prefixes():
    assert RESERVED_EVENT_NAME_PREFIXES == ("introspection.", "gen_ai.")
    assert (
        introspection.RESERVED_EVENT_NAME_PREFIXES
        is RESERVED_EVENT_NAME_PREFIXES
    )


def test_module_log_event_requires_init():
    with pytest.raises(RuntimeError, match="init"):
        introspection.log_event("ark.feed.entry")


def test_module_log_event_routes_through_init_client_alongside_track():
    log_exporter = InMemoryLogRecordExporter()
    introspection.init(
        token="t",
        advanced=AdvancedOptions(
            span_exporter=TestSpanExporter(),
            log_exporter=log_exporter,
            flush_interval_ms=1,
        ),
    )
    introspection.log_event(
        "ark.feed.entry",
        {"entry_id": "e_1"},
        event_id="fe:e_1",
        identity=EventIdentity(user_id="u_1"),
        severity="WARN",
    )
    introspection.track("Button Clicked")
    introspection.get_client().flush()

    records = [d.log_record for d in log_exporter.get_finished_logs()]
    attrs = [dict(r.attributes or {}) for r in records]
    names = [(a[Attr.EVENT_NAME], a[Attr.EVENT_ID]) for a in attrs]
    assert ("ark.feed.entry", "fe:e_1") in names
    assert "Button Clicked" in [n for n, _ in names]
    ((logged, logged_attrs),) = [
        (r, a)
        for r, a in zip(records, attrs, strict=True)
        if a[Attr.EVENT_NAME] == "ark.feed.entry"
    ]
    assert logged_attrs[Attr.USER_ID] == "u_1"
    assert logged.severity_text == "WARN"
