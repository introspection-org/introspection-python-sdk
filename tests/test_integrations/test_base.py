"""Tests for the Integration base class and DidNotEnable exception."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.integrations.base import DidNotEnable, Integration


def test_subclass_requires_identifier():
    with pytest.raises(TypeError, match="identifier"):

        class NoId(Integration):
            @staticmethod
            def setup_once(*, tracer_provider: TracerProvider) -> None: ...


def test_setup_once_must_be_staticmethod():
    with pytest.raises(TypeError, match="staticmethod"):

        class BadSetup(Integration):
            identifier = "bad"

            def setup_once(
                self, *, tracer_provider: TracerProvider
            ) -> None: ...


def test_valid_subclass_constructs():
    class Good(Integration):
        identifier = "good"

        @staticmethod
        def setup_once(*, tracer_provider: TracerProvider) -> None: ...

    assert Good.identifier == "good"
    assert Good.deactivates == frozenset()
    assert Good.min_version is None


def test_did_not_enable_is_exception():
    assert issubclass(DidNotEnable, Exception)
