"""Tests for the built-in integration shims."""

from __future__ import annotations

import importlib

import pytest

SHIMS = {
    "claude_agent": "ClaudeAgentIntegration",
}


@pytest.mark.parametrize("module_name,class_name", SHIMS.items())
def test_shim_class_has_identifier(module_name, class_name):
    module = importlib.import_module(
        f"introspection_sdk.otel.integrations.{module_name}"
    )
    integration = getattr(module, class_name)
    assert isinstance(integration.identifier, str)
    assert integration.identifier
