"""Tests for the integration discovery + setup loader."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.integrations import (
    Integration,
    reset_installed_for_tests,
    setup_integrations,
)


def setup_function():
    reset_installed_for_tests()


def test_setup_runs_once_and_respects_deactivates():
    calls: list[str] = []

    class A(Integration):
        identifier = "a"

        @staticmethod
        def setup_once(*, tracer_provider: TracerProvider) -> None:
            calls.append("a")

    class B(Integration):
        identifier = "b"
        deactivates = frozenset({"a"})

        @staticmethod
        def setup_once(*, tracer_provider: TracerProvider) -> None:
            calls.append("b")

    installed = setup_integrations([A, B], tracer_provider=TracerProvider())
    assert "b" in installed
    assert "a" not in installed  # deactivated by B
    assert calls == ["b"]

    # Second call is a no-op for already-installed identifiers.
    setup_integrations([B], tracer_provider=TracerProvider())
    assert calls == ["b"]


def test_did_not_enable_is_swallowed():
    from introspection_sdk.otel.integrations import DidNotEnable

    class Flaky(Integration):
        identifier = "flaky"

        @staticmethod
        def setup_once(*, tracer_provider: TracerProvider) -> None:
            raise DidNotEnable("nope")

    installed = setup_integrations([Flaky], tracer_provider=TracerProvider())
    assert "flaky" not in installed
