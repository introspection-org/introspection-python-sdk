"""End-to-end test for GeminiIntegration.

Drives the real ``GeminiIntegration.setup_once`` wiring (not the instrumentor
directly) against a recorded Gemini response, asserting a gen_ai span with a
captured thought signature is exported to the shared provider.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from google import genai
from google.genai import types
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from testing import TestSpanExporter

from introspection_sdk.otel.integrations.gemini import GeminiIntegration

pytestmark = pytest.mark.vcr()

GEMINI_MODEL = "gemini-3.1-pro-preview"


@pytest.fixture
def integration_spans(monkeypatch):
    """Wire Gemini via the integration; restore google.genai on teardown."""
    monkeypatch.setenv(
        "GEMINI_API_KEY",
        os.environ.get(
            "GEMINI_API_KEY", "test-dummy-gemini-key-for-vcr-replay"
        ),
    )
    from google.genai import models as genai_models

    saved = {
        "sync_gen": genai_models.Models.generate_content,
        "sync_stream": genai_models.Models.generate_content_stream,
        "async_gen": genai_models.AsyncModels.generate_content,
        "async_stream": genai_models.AsyncModels.generate_content_stream,
    }

    exporter = TestSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    GeminiIntegration.setup_once(tracer_provider=provider)

    try:
        yield exporter
    finally:
        genai_models.Models.generate_content = saved["sync_gen"]
        genai_models.Models.generate_content_stream = saved["sync_stream"]
        genai_models.AsyncModels.generate_content = saved["async_gen"]
        genai_models.AsyncModels.generate_content_stream = saved[
            "async_stream"
        ]


def test_integration_captures_gemini_span(integration_spans: TestSpanExporter):
    client = genai.Client()
    response = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents="What is 2+2? Think step by step.",
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        ),
    )

    assert any(
        bool(p.thought_signature) for p in response.candidates[0].content.parts
    )

    spans = integration_spans.get_finished_spans()
    assert len(spans) >= 1
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.provider.name"] == "gemini"
    assert attrs["gen_ai.request.model"] == GEMINI_MODEL
