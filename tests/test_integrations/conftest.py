"""Isolate these tests from any globally-registered TracerProvider.

``_get_or_create_tracer_provider`` returns the process-global provider when
one is already registered. Other suites in this repo (the logfire-backed
framework tests) register one and OTel refuses to replace it, so without a
reset the get-or-create path here would never run and the assertions would
describe someone else's provider.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace


@pytest.fixture(autouse=True)
def _reset_global_tracer_provider(monkeypatch):
    monkeypatch.setattr(
        trace,
        "_TRACER_PROVIDER_SET_ONCE",
        trace._TRACER_PROVIDER_SET_ONCE.__class__(),
    )
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)
    yield
