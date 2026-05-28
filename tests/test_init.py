"""Tests for the introspection.init() entry point and module proxies."""

from __future__ import annotations

import pytest
from testing import TestSpanExporter

import introspection_sdk.otel as introspection
from introspection_sdk.config import AdvancedOptions
from introspection_sdk.otel import _reset_for_tests
from introspection_sdk.otel.integrations import reset_installed_for_tests
from introspection_sdk.otel.integrations.base import Integration


def setup_function():
    _reset_for_tests()
    reset_installed_for_tests()


def _advanced():
    return AdvancedOptions(span_exporter=TestSpanExporter())


def test_init_is_idempotent():
    p1 = introspection.init(
        token="t", auto_discover=False, advanced=_advanced()
    )
    p2 = introspection.init(token="t", auto_discover=False)
    assert p1 is p2


def test_proxies_require_init():
    _reset_for_tests()
    with pytest.raises(RuntimeError):
        introspection.track("evt")


def test_track_after_init_does_not_raise():
    introspection.init(token="t", auto_discover=False, advanced=_advanced())
    introspection.track("evt", {"k": "v"})


def test_init_installs_requested_integration():
    calls: list[object] = []

    class FakeIntegration(Integration):
        identifier = "fake_test_integration"

        @staticmethod
        def setup_once(*, tracer_provider):
            calls.append(tracer_provider)

    introspection.init(
        token="t",
        auto_discover=False,
        integrations=[FakeIntegration],
        advanced=_advanced(),
    )
    assert len(calls) == 1
