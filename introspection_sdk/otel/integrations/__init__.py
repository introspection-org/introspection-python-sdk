"""Integration registry and loader for ``introspection.init()``."""

from __future__ import annotations

from importlib import import_module
from threading import Lock

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.integrations.base import DidNotEnable, Integration
from introspection_sdk.utils import logger

__all__ = [
    "Integration",
    "DidNotEnable",
    "discover_integrations",
    "setup_integrations",
    "reset_installed_for_tests",
]

# Import paths, resolved lazily so a missing framework just skips its shim.
_BUILTIN_INTEGRATIONS: list[str] = [
    "introspection_sdk.otel.integrations.anthropic.AnthropicIntegration",
    "introspection_sdk.otel.integrations.gemini.GeminiIntegration",
    "introspection_sdk.otel.integrations.openai_agents.OpenAIAgentsIntegration",
    "introspection_sdk.otel.integrations.claude_agent.ClaudeAgentIntegration",
    "introspection_sdk.otel.integrations.langchain.LangchainIntegration",
]

_installed: set[str] = set()
_lock = Lock()


def discover_integrations() -> list[type[Integration]]:
    """Return the built-in integration classes whose framework is importable."""
    found: list[type[Integration]] = []
    for path in _BUILTIN_INTEGRATIONS:
        try:
            mod_path, cls_name = path.rsplit(".", 1)
            module = import_module(mod_path)
            cls = getattr(module, cls_name)
            found.append(cls)
        except (DidNotEnable, ImportError, SyntaxError) as e:
            logger.debug("Skipping integration %s: %s", path, e)
    return found


def setup_integrations(
    integrations: list[type[Integration]],
    *,
    tracer_provider: TracerProvider,
) -> set[str]:
    """Run each integration's ``setup_once`` once, honouring ``deactivates``.

    Returns the set of identifiers installed so far this process.
    """
    by_id: dict[str, type[Integration]] = {}
    for cls in integrations:
        by_id.setdefault(cls.identifier, cls)

    disabled: set[str] = set()
    for cls in by_id.values():
        disabled.update(cls.deactivates)

    for identifier, cls in by_id.items():
        if identifier in disabled:
            logger.debug(
                "Skipping %s (deactivated by another integration)", identifier
            )
            continue
        with _lock:
            if identifier in _installed:
                continue
            try:
                cls.setup_once(tracer_provider=tracer_provider)
            except DidNotEnable as e:
                logger.debug("Could not enable %s: %s", identifier, e)
                continue
            _installed.add(identifier)

    return set(_installed)


def reset_installed_for_tests() -> None:
    """Clear the run-once guard. Test-only utility."""
    with _lock:
        _installed.clear()
