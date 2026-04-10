"""Claude Agent SDK + LangSmith dual-export integration tests.

Tests that configure_claude_agent_sdk() + IntrospectionSpanProcessor on the
global TracerProvider can be set up together for dual export.

The Claude SDK uses subprocess IPC (not HTTP), so VCR cannot record its
interactions. These tests verify the setup/plumbing works correctly.
"""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from testing import TestSpanExporter

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.config import AdvancedOptions

try:
    from claude_agent_sdk import ClaudeAgentOptions
    from langsmith.integrations.claude_agent_sdk import (
        configure_claude_agent_sdk,
    )

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

pytestmark = pytest.mark.skipif(
    not HAS_DEPS,
    reason="claude-agent-sdk or langsmith dependencies not installed",
)


@pytest.fixture
def introspection_exporter() -> Iterator[TestSpanExporter]:
    """Set up global TracerProvider with IntrospectionSpanProcessor.

    Yields TestSpanExporter for assertions.
    """
    exporter = TestSpanExporter()
    processor = IntrospectionSpanProcessor(
        token="test-token",
        advanced=AdvancedOptions(span_exporter=exporter),
    )

    provider = TracerProvider()
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    try:
        yield exporter
    finally:
        processor.force_flush()
        processor.shutdown()


def test_configure_claude_agent_sdk_setup(introspection_exporter):
    """Test that configure_claude_agent_sdk() can be called alongside
    IntrospectionSpanProcessor without errors."""
    configure_claude_agent_sdk()


def test_claude_agent_options_creation():
    """Test that ClaudeAgentOptions can be created with model and system prompt."""
    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="You are a helpful assistant.",
        include_partial_messages=True,
    )
    assert options.model == "claude-sonnet-4-5-20250929"
    assert options.system_prompt == "You are a helpful assistant."
    assert options.include_partial_messages is True


def test_dual_setup_tracer_provider_active(introspection_exporter):
    """Test that the global TracerProvider is active after dual setup."""
    configure_claude_agent_sdk()

    # Verify TracerProvider is set and functional
    provider = trace.get_tracer_provider()
    assert provider is not None

    tracer = provider.get_tracer("test")
    assert tracer is not None
