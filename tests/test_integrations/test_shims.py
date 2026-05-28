"""Tests for the built-in integration shims."""

from __future__ import annotations

import importlib

import pytest

SHIMS = {
    "anthropic": "AnthropicIntegration",
    "openai_agents": "OpenAIAgentsIntegration",
    "claude_agent": "ClaudeAgentIntegration",
    "langchain": "LangchainIntegration",
    "gemini": "GeminiIntegration",
}


@pytest.mark.parametrize("module_name,class_name", SHIMS.items())
def test_shim_class_has_identifier(module_name, class_name):
    module = importlib.import_module(
        f"introspection_sdk.otel.integrations.{module_name}"
    )
    integration = getattr(module, class_name)
    assert isinstance(integration.identifier, str)
    assert integration.identifier


def test_langchain_deactivates_anthropic():
    from introspection_sdk.otel.integrations.langchain import (
        LangchainIntegration,
    )

    assert "anthropic" in LangchainIntegration.deactivates


def test_gemini_setup_once_passes_shared_provider(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider

    import introspection_sdk.otel.gemini as gemini_module
    from introspection_sdk.otel.integrations.gemini import GeminiIntegration

    captured = {}

    def fake_instrument(self, tracer_provider=None):
        captured["provider"] = tracer_provider

    monkeypatch.setattr(
        gemini_module.GeminiInstrumentor, "instrument", fake_instrument
    )
    provider = TracerProvider()
    GeminiIntegration.setup_once(tracer_provider=provider)
    assert captured["provider"] is provider
