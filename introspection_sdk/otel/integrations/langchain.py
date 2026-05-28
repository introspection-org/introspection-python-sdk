"""LangChain / LangGraph integration.

The handler is bound to the shared TracerProvider here; attach it per invoke via
``chain.invoke(..., config={"callbacks": [get_handler()]})``. Global auto-attach
is deferred (see docs/unified-sdk-architecture.md).
"""

from __future__ import annotations

try:
    from langchain_core.callbacks import BaseCallbackManager  # noqa: F401
except ImportError as e:
    from introspection_sdk.otel.integrations.base import DidNotEnable

    raise DidNotEnable("langchain-core package not installed") from e

from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk.otel.integrations.base import Integration
from introspection_sdk.otel.processors.langchain_callback_handler import (
    IntrospectionCallbackHandler,
)
from introspection_sdk.utils import logger

_handler: IntrospectionCallbackHandler | None = None


def get_handler() -> IntrospectionCallbackHandler:
    """Return the handler bound by ``init()``; raises if ``init()`` hasn't run."""
    if _handler is None:
        raise RuntimeError(
            "LangChain integration not configured. Call introspection.init() first."
        )
    return _handler


class LangchainIntegration(Integration):
    identifier = "langchain"
    deactivates = frozenset({"anthropic"})

    @staticmethod
    def setup_once(*, tracer_provider: TracerProvider) -> None:
        global _handler
        _handler = IntrospectionCallbackHandler(
            tracer_provider=tracer_provider
        )
        logger.info(
            "Introspection LangChain handler ready. Attach via config="
            "{'callbacks': [introspection_sdk.otel.integrations.langchain.get_handler()]}."
        )
