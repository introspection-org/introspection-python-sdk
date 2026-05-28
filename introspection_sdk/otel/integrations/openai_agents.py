"""OpenAI Agents SDK integration."""

from __future__ import annotations

try:
    from agents import add_trace_processor  # noqa: F401
except ImportError as e:
    from introspection_sdk.otel.integrations.base import DidNotEnable

    raise DidNotEnable("openai-agents package not installed") from e

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.integrations.base import Integration
from introspection_sdk.otel.processors.tracing_processor import (
    IntrospectionTracingProcessor,
)


class OpenAIAgentsIntegration(Integration):
    identifier = "openai_agents"

    @staticmethod
    def setup_once(*, tracer_provider: TracerProvider) -> None:
        # add_trace_processor appends, preserving any processors other
        # integrations (e.g. LangSmith) already registered.
        from agents import add_trace_processor

        add_trace_processor(
            IntrospectionTracingProcessor(tracer_provider=tracer_provider)
        )
