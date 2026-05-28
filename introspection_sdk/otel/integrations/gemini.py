"""Gemini (google-genai) integration.

Wires this SDK's GeminiInstrumentor into the shared provider. The instrumentor
captures Gemini thought signatures (encrypted reasoning tokens) that third-party
instrumentors drop; that capture logic is unchanged here.
"""

from __future__ import annotations

try:
    import google.genai  # noqa: F401
except ImportError as e:
    from introspection_sdk.otel.integrations.base import DidNotEnable

    raise DidNotEnable("google-genai package not installed") from e

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.gemini import GeminiInstrumentor
from introspection_sdk.otel.integrations.base import Integration


class GeminiIntegration(Integration):
    identifier = "gemini"

    @staticmethod
    def setup_once(*, tracer_provider: TracerProvider) -> None:
        GeminiInstrumentor().instrument(tracer_provider=tracer_provider)
