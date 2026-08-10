"""Tests for :mod:`introspection_sdk.otel._endpoint`.

The span and log exporters read the same ``base_url`` setting, so a value
that works for one has to work for the other. These assert the three
spellings a caller can reasonably supply.
"""

from __future__ import annotations

import pytest

from introspection_sdk.otel._endpoint import otlp_endpoint


def test_bare_base_gets_the_signal_path():
    assert (
        otlp_endpoint("https://otel.introspection.dev", "traces")
        == "https://otel.introspection.dev/v1/traces"
    )
    assert (
        otlp_endpoint("https://otel.introspection.dev/", "logs")
        == "https://otel.introspection.dev/v1/logs"
    )


def test_path_prefix_survives():
    # A relative join; an absolute "/v1/traces" would discard "/otlp".
    assert (
        otlp_endpoint("https://gateway.internal/otlp", "traces")
        == "https://gateway.internal/otlp/v1/traces"
    )
    assert (
        otlp_endpoint("https://gateway.internal/otlp", "logs")
        == "https://gateway.internal/otlp/v1/logs"
    )


def test_a_base_carrying_one_signal_suffix_still_resolves_the_other():
    # AdvancedOptions documents "http://localhost:5418/v1/traces" as a valid
    # base; the logs exporter must not append a second suffix to it.
    base = "http://localhost:5418/v1/traces"
    assert otlp_endpoint(base, "traces") == "http://localhost:5418/v1/traces"
    assert otlp_endpoint(base, "logs") == "http://localhost:5418/v1/logs"


def test_unknown_signal_raises():
    with pytest.raises(ValueError, match="Unknown OTLP signal"):
        otlp_endpoint("https://otel.introspection.dev", "metrics")
