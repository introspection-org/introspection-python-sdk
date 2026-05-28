"""Shared-provider mode for IntrospectionCallbackHandler."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider

pytest.importorskip("langchain_core")

from introspection_sdk.otel.processors.langchain_callback_handler import (  # noqa: E402
    IntrospectionCallbackHandler,
)


def test_uses_passed_provider():
    provider = TracerProvider()
    handler = IntrospectionCallbackHandler(tracer_provider=provider)
    assert handler._provider is provider
    assert handler._owns_provider is False
