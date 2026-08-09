"""Tests for the introspection.init() entry point and module proxies."""

from __future__ import annotations

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from testing import TestSpanExporter

import introspection_sdk.otel as introspection
from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel import _reset_for_tests


def setup_function():
    _reset_for_tests()


def _advanced():
    # Both exporters must be in-memory. init() always builds an
    # IntrospectionLogs, so leaving log_exporter unset points the logs stream
    # at the production OTLP endpoint and the atexit flush ships whatever
    # these tests tracked.
    return AdvancedOptions(
        span_exporter=TestSpanExporter(),
        log_exporter=InMemoryLogRecordExporter(),
    )


def test_init_is_idempotent():
    p1 = introspection.init(token="t", advanced=_advanced())
    p2 = introspection.init(token="t")
    assert p1 is p2


def test_proxies_require_init():
    _reset_for_tests()
    with pytest.raises(RuntimeError):
        introspection.track("evt")


def test_track_after_init_does_not_raise():
    introspection.init(token="t", advanced=_advanced())
    introspection.track("evt", {"k": "v"})
