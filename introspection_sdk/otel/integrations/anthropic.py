"""Anthropic SDK integration."""

from __future__ import annotations

try:
    import anthropic  # noqa: F401
except ImportError as e:
    from introspection_sdk.otel.integrations.base import DidNotEnable

    raise DidNotEnable("anthropic package not installed") from e

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.anthropic import AnthropicInstrumentor
from introspection_sdk.otel.integrations.base import Integration


class AnthropicIntegration(Integration):
    identifier = "anthropic"

    @staticmethod
    def setup_once(*, tracer_provider: TracerProvider) -> None:
        AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
