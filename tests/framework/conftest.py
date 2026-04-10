"""Pytest fixtures for framework integration tests."""

import os
from collections.abc import Iterator

import logfire
import pytest
from conftest import CaptureSpanProcessor, CaptureTracingProcessor
from openai import AsyncOpenAI
from testing import TestSpanExporter

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.config import AdvancedOptions

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from agents import set_trace_processors

    from introspection_sdk import IntrospectionTracingProcessor

    HAS_AGENTS = True
except (ImportError, RuntimeError):
    HAS_AGENTS = False

DUMMY_OPENAI_KEY = "sk-test-dummy-key-for-vcr-replay"
DUMMY_ANTHROPIC_KEY = "sk-ant-test-dummy-key-for-vcr-replay"


@pytest.fixture(autouse=True)
def _configure_logfire(monkeypatch):
    """Ensure logfire is configured and dummy API keys are set for VCR replay."""
    monkeypatch.setenv(
        "OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", DUMMY_OPENAI_KEY)
    )
    monkeypatch.setenv(
        "ANTHROPIC_API_KEY",
        os.environ.get("ANTHROPIC_API_KEY", DUMMY_ANTHROPIC_KEY),
    )
    logfire.configure(
        send_to_logfire=False,
        console=False,
    )


@pytest.fixture
def openai_async_client() -> AsyncOpenAI:
    """OpenAI async client instrumented with logfire."""
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", DUMMY_OPENAI_KEY)
    )
    logfire.instrument_openai(client)
    return client


@pytest.fixture
def anthropic_async_client():
    """Anthropic async client instrumented with logfire."""
    if not HAS_ANTHROPIC:
        pytest.skip("anthropic not installed")
    client = anthropic.AsyncAnthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY", DUMMY_ANTHROPIC_KEY)
    )
    logfire.instrument_anthropic(client)
    return client


@pytest.fixture
def cap_span_processor() -> Iterator[CaptureSpanProcessor]:
    """Configure logfire with IntrospectionSpanProcessor for capturing spans."""
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
    try:
        yield CaptureSpanProcessor(exporter=exporter, processor=processor)
    finally:
        processor.shutdown()


@pytest.fixture
def cap_tracing_processor() -> Iterator[CaptureTracingProcessor]:
    """Configure IntrospectionTracingProcessor for capturing agent traces."""
    if not HAS_AGENTS:
        pytest.skip("openai-agents not installed")
    exporter = TestSpanExporter()
    processor = IntrospectionTracingProcessor(
        advanced=AdvancedOptions(span_exporter=exporter),
    )
    set_trace_processors([processor])
    logfire.configure(
        send_to_logfire=False,
        console=False,
    )
    try:
        yield CaptureTracingProcessor(exporter=exporter, processor=processor)
    finally:
        processor.shutdown()
