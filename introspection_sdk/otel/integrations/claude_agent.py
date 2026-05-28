"""Claude Agent SDK integration."""

from __future__ import annotations

try:
    import claude_agent_sdk  # noqa: F401
except ImportError as e:
    from introspection_sdk.otel.integrations.base import DidNotEnable

    raise DidNotEnable("claude-agent-sdk package not installed") from e

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.integrations.base import Integration
from introspection_sdk.otel.processors.claude_tracing_processor import (
    ClaudeTracingProcessor,
)


class ClaudeAgentIntegration(Integration):
    identifier = "claude_agent"

    @staticmethod
    def setup_once(*, tracer_provider: TracerProvider) -> None:
        ClaudeTracingProcessor(tracer_provider=tracer_provider).configure()
