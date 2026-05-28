"""Pytest fixtures for observability dual-export tests."""

import base64
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from testing import TestSpanExporter

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.config import AdvancedOptions

try:
    from openinference.instrumentation.openai import OpenAIInstrumentor

    HAS_OPENINFERENCE = True
except ImportError:
    HAS_OPENINFERENCE = False
    OpenAIInstrumentor: Any = None

try:
    from openinference.instrumentation.anthropic import AnthropicInstrumentor

    HAS_OPENINFERENCE_ANTHROPIC = True
except ImportError:
    HAS_OPENINFERENCE_ANTHROPIC = False
    AnthropicInstrumentor: Any = None

try:
    from openinference.instrumentation.openai_agents import (
        OpenAIAgentsInstrumentor,
    )

    HAS_OPENINFERENCE_AGENTS = True
except ImportError:
    HAS_OPENINFERENCE_AGENTS = False
    OpenAIAgentsInstrumentor: Any = None

try:
    from phoenix.otel import register as phoenix_register

    HAS_ARIZE = True
except ImportError:
    HAS_ARIZE = False
    phoenix_register: Any = None

try:
    from openinference.instrumentation.langchain import LangChainInstrumentor

    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False
    LangChainInstrumentor: Any = None

try:
    from braintrust.otel import BraintrustSpanProcessor

    HAS_BRAINTRUST = True
except ImportError:
    HAS_BRAINTRUST = False
    BraintrustSpanProcessor: Any = None

try:
    from langfuse import get_client as langfuse_get_client

    HAS_LANGFUSE = True
except ImportError:
    HAS_LANGFUSE = False
    langfuse_get_client: Any = None


@dataclass
class CaptureOpenInferenceSpans:
    """Holds the span exporter and processor for OpenInference testing."""

    exporter: TestSpanExporter
    processor: IntrospectionSpanProcessor


DUMMY_OPENAI_KEY = "sk-test-dummy-key-for-vcr-replay"
DUMMY_ANTHROPIC_KEY = "sk-ant-test-dummy-key-for-vcr-replay"
DUMMY_INTROSPECTION_TOKEN = "test-introspection-token"
DUMMY_BRAINTRUST_API_KEY = "bt-test-dummy-key"
DUMMY_LANGSMITH_API_KEY = "lsv2-test-dummy-key"
DUMMY_LANGFUSE_PUBLIC_KEY = "pk-lf-test-dummy"
DUMMY_LANGFUSE_SECRET_KEY = "sk-lf-test-dummy"


@pytest.fixture(autouse=True)
def _reset_otel_state(monkeypatch):
    """Reset the global OTel TracerProvider state and set dummy env vars.

    Configure logfire with send_to_logfire=False to suppress
    LogfireNotConfiguredWarning in tests that use logfire instrumentation.

    This prevents state leakage between tests that each set up their
    own TracerProvider (arize, braintrust, langchain, langfuse).
    """
    monkeypatch.setenv(
        "OPENAI_API_KEY",
        os.environ.get("OPENAI_API_KEY", DUMMY_OPENAI_KEY),
    )
    monkeypatch.setenv(
        "ANTHROPIC_API_KEY",
        os.environ.get("ANTHROPIC_API_KEY", DUMMY_ANTHROPIC_KEY),
    )
    monkeypatch.setenv(
        "INTROSPECTION_TOKEN",
        os.environ.get("INTROSPECTION_TOKEN", DUMMY_INTROSPECTION_TOKEN),
    )
    monkeypatch.setenv(
        "BRAINTRUST_API_KEY",
        os.environ.get("BRAINTRUST_API_KEY", DUMMY_BRAINTRUST_API_KEY),
    )
    monkeypatch.setenv(
        "LANGSMITH_API_KEY",
        os.environ.get("LANGSMITH_API_KEY", DUMMY_LANGSMITH_API_KEY),
    )
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_OTEL_ENABLED", "true")
    monkeypatch.setenv(
        "LANGFUSE_PUBLIC_KEY",
        os.environ.get("LANGFUSE_PUBLIC_KEY", DUMMY_LANGFUSE_PUBLIC_KEY),
    )
    monkeypatch.setenv(
        "LANGFUSE_SECRET_KEY",
        os.environ.get("LANGFUSE_SECRET_KEY", DUMMY_LANGFUSE_SECRET_KEY),
    )
    monkeypatch.setenv("LOGFIRE_IGNORE_NO_CONFIG", "1")
    trace._TRACER_PROVIDER_SET_ONCE = (
        trace._TRACER_PROVIDER_SET_ONCE.__class__()
    )
    trace._TRACER_PROVIDER = None
    yield
    trace._TRACER_PROVIDER_SET_ONCE = (
        trace._TRACER_PROVIDER_SET_ONCE.__class__()
    )
    trace._TRACER_PROVIDER = None


@pytest.fixture
def arize_provider() -> Iterator[CaptureOpenInferenceSpans]:
    """Fixture for Arize/Phoenix dual export testing.

    Sets up:
    - Phoenix TracerProvider via register()
    - IntrospectionSpanProcessor with TestSpanExporter
    - OpenAIInstrumentor for capturing OpenAI calls

    Yields CaptureOpenInferenceSpans with exporter for assertions.
    """
    if not HAS_ARIZE:
        pytest.fail(
            "Arize Phoenix dependencies not installed. "
            "Install with: uv sync --group arize"
        )
    if not HAS_OPENINFERENCE:
        pytest.fail(
            "OpenInference dependencies not installed. "
            "Install with: uv sync --group arize"
        )
    assert phoenix_register is not None
    assert OpenAIInstrumentor is not None

    tracer_provider = phoenix_register(
        project_name="dual-export-test",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ.get("ARIZE_SPACE_KEY", ""),
            "api_key": os.environ.get("ARIZE_API_KEY", ""),
        },
        batch=False,
    )

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    tracer_provider.add_span_processor(
        processor,
    )

    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        OpenAIInstrumentor().uninstrument()
        processor.force_flush()
        processor.shutdown()


@pytest.fixture
def braintrust_provider() -> Iterator[CaptureOpenInferenceSpans]:
    """Fixture for Braintrust dual export testing.

    Sets up:
    - Manual TracerProvider
    - Braintrust OTLP processor for dual export to Braintrust
    - IntrospectionSpanProcessor with TestSpanExporter
    - OpenAIInstrumentor for capturing OpenAI calls

    Yields CaptureOpenInferenceSpans with exporter for assertions.
    """
    if not HAS_BRAINTRUST:
        pytest.fail(
            "Braintrust dependencies not installed. "
            "Install with: uv sync --group braintrust"
        )
    if not HAS_OPENINFERENCE:
        pytest.fail(
            "OpenInference dependencies not installed. "
            "Install with: uv sync --group arize"
        )
    assert OpenAIInstrumentor is not None

    provider = TracerProvider()

    braintrust_processor = IntrospectionSpanProcessor(
        token=os.environ.get("BRAINTRUST_API_KEY", DUMMY_BRAINTRUST_API_KEY),
        advanced=AdvancedOptions(
            base_url="https://api.braintrust.dev/otel/v1/traces",
            additional_headers={
                "x-bt-parent": "project_name:dual-export-test",
            },
        ),
    )
    provider.add_span_processor(braintrust_processor)

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)

    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        OpenAIInstrumentor().uninstrument()
        braintrust_processor.force_flush()
        processor.force_flush()
        braintrust_processor.shutdown()
        processor.shutdown()


@pytest.fixture
def langchain_provider() -> Iterator[CaptureOpenInferenceSpans]:
    """Fixture for LangChain/LangSmith dual export testing.

    Sets up:
    - Manual TracerProvider
    - LangSmith OTLP BatchSpanProcessor for dual export to LangSmith
    - IntrospectionSpanProcessor with TestSpanExporter
    - LangChainInstrumentor for capturing LangChain calls

    Yields CaptureOpenInferenceSpans with exporter for assertions.
    """
    if not HAS_LANGCHAIN:
        pytest.fail(
            "LangChain dependencies not installed. "
            "Install with: uv sync --group langchain"
        )
    assert LangChainInstrumentor is not None

    provider = TracerProvider()

    langsmith_exporter = OTLPSpanExporter(
        endpoint="https://api.smith.langchain.com/otel/v1/traces",
        headers={
            "x-api-key": os.environ.get("LANGSMITH_API_KEY", ""),
            "Langsmith-Project": os.environ.get("LANGSMITH_PROJECT", ""),
        },
    )
    langsmith_processor = BatchSpanProcessor(langsmith_exporter)
    provider.add_span_processor(langsmith_processor)

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)
    LangChainInstrumentor().instrument(tracer_provider=provider)

    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        LangChainInstrumentor().uninstrument()
        langsmith_processor.force_flush()
        processor.force_flush()
        langsmith_processor.shutdown()
        processor.shutdown()


@pytest.fixture
def langfuse_provider(monkeypatch) -> Iterator[CaptureOpenInferenceSpans]:
    """Fixture for Langfuse dual export testing using OTEL SDK pattern.

    Sets up:
    - IntrospectionSpanProcessor with TestSpanExporter
    - OpenAIInstrumentor for capturing OpenAI calls

    Yields CaptureOpenInferenceSpans with exporter for assertions.
    """
    if not HAS_LANGFUSE:
        pytest.fail(
            "Langfuse dependencies not installed. "
            "Install with: uv sync --group langfuse"
        )
    if not HAS_OPENINFERENCE:
        pytest.fail(
            "OpenInference dependencies not installed. "
            "Install with: uv sync --group arize"
        )
    assert langfuse_get_client is not None
    assert OpenAIInstrumentor is not None

    langfuse_auth = base64.b64encode(
        f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
    ).decode()

    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        + "/api/public/otel",
    )
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS", f"Authorization=Basic {langfuse_auth}"
    )

    monkeypatch.setattr(
        trace,
        "_TRACER_PROVIDER_SET_ONCE",
        trace._TRACER_PROVIDER_SET_ONCE.__class__(),
    )
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)

    provider = TracerProvider()

    langfuse_processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(langfuse_processor)

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    langfuse = langfuse_get_client()

    OpenAIInstrumentor().instrument(tracer_provider=provider)

    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        langfuse.flush()
        OpenAIInstrumentor().uninstrument()
        langfuse_processor.force_flush()
        processor.force_flush()
        langfuse_processor.shutdown()
        processor.shutdown()


@pytest.fixture
def langfuse_anthropic_provider(
    monkeypatch,
) -> Iterator[CaptureOpenInferenceSpans]:
    """Langfuse dual export for Anthropic via OpenInference.

    Mirrors ``langfuse_provider`` but uses ``AnthropicInstrumentor``
    so Anthropic SDK calls flow into both Langfuse and Introspection.
    """
    if not HAS_LANGFUSE:
        pytest.fail("Install with: uv sync --group langfuse")
    if not HAS_OPENINFERENCE_ANTHROPIC:
        pytest.fail(
            "openinference-instrumentation-anthropic not installed; "
            "it's part of the test extras."
        )
    assert langfuse_get_client is not None
    assert AnthropicInstrumentor is not None

    langfuse_auth = base64.b64encode(
        f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
    ).decode()
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        + "/api/public/otel",
    )
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"Authorization=Basic {langfuse_auth}",
    )
    monkeypatch.setattr(
        trace,
        "_TRACER_PROVIDER_SET_ONCE",
        trace._TRACER_PROVIDER_SET_ONCE.__class__(),
    )
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)

    provider = TracerProvider()
    langfuse_processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(langfuse_processor)

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    langfuse = langfuse_get_client()
    AnthropicInstrumentor().instrument(tracer_provider=provider)
    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        langfuse.flush()
        AnthropicInstrumentor().uninstrument()
        langfuse_processor.force_flush()
        processor.force_flush()
        langfuse_processor.shutdown()
        processor.shutdown()


@pytest.fixture
def arize_anthropic_provider() -> Iterator[CaptureOpenInferenceSpans]:
    """Arize/Phoenix dual export for Anthropic via OpenInference.

    Mirrors ``arize_provider`` but uses ``AnthropicInstrumentor``.
    """
    if not HAS_ARIZE:
        pytest.fail("Install with: uv sync --group arize")
    if not HAS_OPENINFERENCE_ANTHROPIC:
        pytest.fail(
            "openinference-instrumentation-anthropic not installed; "
            "it's part of the test extras."
        )
    assert phoenix_register is not None
    assert AnthropicInstrumentor is not None

    tracer_provider = phoenix_register(
        project_name="dual-export-test",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ.get("ARIZE_SPACE_KEY", ""),
            "api_key": os.environ.get("ARIZE_API_KEY", ""),
        },
        batch=False,
    )

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    tracer_provider.add_span_processor(processor)

    AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        AnthropicInstrumentor().uninstrument()
        processor.force_flush()
        processor.shutdown()


@pytest.fixture
def arize_agents_provider() -> Iterator[CaptureOpenInferenceSpans]:
    """Arize/Phoenix dual export for OpenAI Agents via OpenInference."""
    if not HAS_ARIZE:
        pytest.fail("Install with: uv sync --group arize")
    if not HAS_OPENINFERENCE_AGENTS:
        pytest.fail(
            "openinference-instrumentation-openai-agents not installed; "
            "it's part of the test extras."
        )
    assert phoenix_register is not None
    assert OpenAIAgentsInstrumentor is not None

    tracer_provider = phoenix_register(
        project_name="dual-export-test",
        endpoint="https://otlp.arize.com/v1/traces",
        headers={
            "space_id": os.environ.get("ARIZE_SPACE_KEY", ""),
            "api_key": os.environ.get("ARIZE_API_KEY", ""),
        },
        batch=False,
    )

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    tracer_provider.add_span_processor(processor)

    OpenAIAgentsInstrumentor().instrument(tracer_provider=tracer_provider)
    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        OpenAIAgentsInstrumentor().uninstrument()
        processor.force_flush()
        processor.shutdown()


@pytest.fixture
def langfuse_agents_provider(
    monkeypatch,
) -> Iterator[CaptureOpenInferenceSpans]:
    """Langfuse dual export for OpenAI Agents via OpenInference."""
    if not HAS_LANGFUSE:
        pytest.fail("Install with: uv sync --group langfuse")
    if not HAS_OPENINFERENCE_AGENTS:
        pytest.fail(
            "openinference-instrumentation-openai-agents not installed; "
            "it's part of the test extras."
        )
    assert langfuse_get_client is not None
    assert OpenAIAgentsInstrumentor is not None

    langfuse_auth = base64.b64encode(
        f"{os.environ.get('LANGFUSE_PUBLIC_KEY')}:{os.environ.get('LANGFUSE_SECRET_KEY')}".encode()
    ).decode()
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        + "/api/public/otel",
    )
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"Authorization=Basic {langfuse_auth}",
    )
    monkeypatch.setattr(
        trace,
        "_TRACER_PROVIDER_SET_ONCE",
        trace._TRACER_PROVIDER_SET_ONCE.__class__(),
    )
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None)

    provider = TracerProvider()
    langfuse_processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(langfuse_processor)

    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token=os.environ.get("INTROSPECTION_TOKEN"),
        advanced=AdvancedOptions(
            base_url=os.environ.get("INTROSPECTION_BASE_URL"),
            span_exporter=exporter,
        ),
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    langfuse = langfuse_get_client()
    OpenAIAgentsInstrumentor().instrument(tracer_provider=provider)
    try:
        yield CaptureOpenInferenceSpans(exporter=exporter, processor=processor)
    finally:
        langfuse.flush()
        OpenAIAgentsInstrumentor().uninstrument()
        langfuse_processor.force_flush()
        processor.force_flush()
        langfuse_processor.shutdown()
        processor.shutdown()
