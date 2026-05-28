"""Gemini native tests without thinking: baseline, tools, structured output.

Thought-signature coverage lives in ``test_gemini_thinking.py``; this file
covers the non-thinking paths called out in docs/test-quality-audit-plan.md
(Phase 3b). Uses ``GeminiInstrumentor`` via the same logfire + test-exporter
setup, recorded against the live ``google-genai`` API.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, cast

import pytest
from conftest import CaptureSpanProcessor
from dirty_equals import IsInt, IsPartialDict, IsStr
from google import genai
from google.genai import types
from testing import TestSpanExporter

from introspection_sdk import (
    AdvancedOptions,
    GeminiInstrumentor,
    IntrospectionSpanProcessor,
)

pytestmark = pytest.mark.vcr()

GEMINI_MODEL = "gemini-3.1-pro-preview"


@pytest.fixture
def cap_gemini_processor(monkeypatch):
    """GeminiInstrumentor wired into logfire with a test exporter."""
    import logfire

    monkeypatch.setenv(
        "GEMINI_API_KEY",
        os.environ.get(
            "GEMINI_API_KEY", "test-dummy-gemini-key-for-vcr-replay"
        ),
    )

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token="test-token",
        advanced=AdvancedOptions(span_exporter=exporter),
    )
    logfire.configure(
        send_to_logfire=False,
        additional_span_processors=[processor],
        console=False,
    )

    instrumentor = GeminiInstrumentor()
    instrumentor.instrument()
    try:
        yield CaptureSpanProcessor(exporter=exporter, processor=processor)
    finally:
        instrumentor.uninstrument()
        processor.shutdown()


def _gemini_span(cap: CaptureSpanProcessor) -> dict:
    cap.processor.force_flush()
    spans = cap.exporter.get_finished_spans()
    chat = [
        s
        for s in spans
        if s["attributes"].get("gen_ai.provider.name") == "gemini"
    ]
    assert chat, (
        "expected a gemini span; got "
        f"{[s['attributes'].get('gen_ai.provider.name') for s in spans]}"
    )
    return chat[0]


def test_gemini_baseline_no_thinking(
    cap_gemini_processor: CaptureSpanProcessor,
):
    """Plain text generation, no thinking config."""
    client = genai.Client()
    response = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents="What is the capital of France? Answer in one word.",
    )
    assert response.text

    span = _gemini_span(cap_gemini_processor)
    assert span["attributes"] == IsPartialDict(
        {
            "gen_ai.provider.name": "gemini",
            "gen_ai.request.model": GEMINI_MODEL,
            "gen_ai.usage.input_tokens": IsInt(),
            "gen_ai.usage.output_tokens": IsInt(),
        }
    )


def test_gemini_function_calling(cap_gemini_processor: CaptureSpanProcessor):
    """Function calling captured as a tool_call part."""
    client = genai.Client()
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_weather",
                description="Get weather for a city.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={"city": types.Schema(type=types.Type.STRING)},
                    required=["city"],
                ),
            )
        ]
    )
    response = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents="Use the get_weather tool for Tokyo.",
        config=types.GenerateContentConfig(tools=[tool]),
    )
    calls = [
        p.function_call
        for c in response.candidates
        for p in c.content.parts
        if getattr(p, "function_call", None)
    ]
    assert calls and calls[0].name == "get_weather"

    span = _gemini_span(cap_gemini_processor)
    assert "tool_call" in str(
        span["attributes"].get("gen_ai.output.messages", "")
    )


def test_gemini_structured_output(cap_gemini_processor: CaptureSpanProcessor):
    """Structured JSON output via response_schema."""
    client = genai.Client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=types.Schema(
            type=types.Type.OBJECT,
            properties={"answer": types.Schema(type=types.Type.STRING)},
            required=["answer"],
        ),
    )
    response = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents="What is 2+2? Respond with JSON key 'answer'.",
        config=config,
    )
    data = json.loads(response.text)
    assert "answer" in data

    span = _gemini_span(cap_gemini_processor)
    assert span["attributes"] == IsPartialDict(
        {"gen_ai.provider.name": "gemini", "gen_ai.request.model": IsStr()}
    )


# 64x64 solid red PNG.
_RED_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAeUlEQVR4nO3PQQkA"
    "MAzAwCqpf1ETMxF7HINABFzm7H7dcEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQ"
    "gBY0oAUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjSg"
    "BQ1oQQNa0IAWNKAFj13PLIEAOXyUUwAAAABJRU5ErkJggg=="
)


def test_gemini_error_invalid_model(
    cap_gemini_processor: CaptureSpanProcessor,
):
    """Error path: an invalid model raises a google-genai API error."""
    from google.genai import errors as genai_errors

    client = genai.Client()
    with pytest.raises(genai_errors.APIError):
        cast(Any, client.models.generate_content)(
            model="gemini-nonexistent-xyz",
            contents="hi",
        )


def test_gemini_vision(cap_gemini_processor: CaptureSpanProcessor):
    """Vision / image input via Part.from_bytes."""
    client = genai.Client()
    response = cast(Any, client.models.generate_content)(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(
                data=base64.b64decode(_RED_PNG), mime_type="image/png"
            ),
            "What colour is this image? One word.",
        ],
    )
    assert response.text

    span = _gemini_span(cap_gemini_processor)
    assert span["attributes"] == IsPartialDict(
        {"gen_ai.provider.name": "gemini", "gen_ai.request.model": IsStr()}
    )
