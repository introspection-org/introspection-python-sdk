"""OpenTelemetry-only type / constant definitions.

These were extracted from a former top-level ``types`` module
module so the REST-only install can avoid pulling them in. They cover
OTel attribute keys, baggage keys, event names, and feedback property
shapes used by :class:`~introspection_sdk.otel.logs.IntrospectionLogs`
and the span / tracing processors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Attr",
    "Baggage",
    "EventName",
    "FeedbackProperties",
]


class EventName:
    """Standard event names used by the Introspection SDK."""

    IDENTIFY = "identify"
    FEEDBACK = "introspection.feedback"


class Attr:
    """Standard log attribute keys used by the Introspection SDK.

    These follow OpenTelemetry semantic conventions where applicable.
    """

    # Core event fields
    EVENT_NAME = "event.name"
    EVENT_ID = "event.id"

    # Identity
    USER_ID = "identity.user.id"
    ANONYMOUS_ID = "identity.anonymous.id"

    # Gen AI (OTel semantic conventions)
    CONVERSATION_ID = "gen_ai.conversation.id"
    PREVIOUS_RESPONSE_ID = "gen_ai.request.previous_response_id"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_ID = "gen_ai.agent.id"

    # Introspection-namespaced span attributes. The SDK emits no spans of its
    # own, so nothing here writes them — they are the names hand-written and
    # harness instrumentation must use to stay consistent with the other
    # SDKs. TERMINATION_REASON="cancelled" alongside
    # gen_ai.response.finish_reasons=["aborted"] and an Unset status is how a
    # caller-requested abort is distinguished from a failure.
    TERMINATION_REASON = "introspection.termination_reason"
    LLM_COST_USD = "introspection.llm.cost_usd"
    LLM_UPSTREAM_COST_USD = "introspection.llm.upstream_cost_usd"

    # Prefixes for dynamic keys
    PROPERTIES_PREFIX = "properties."
    TRAITS_PREFIX = "context.traits."


class Baggage:
    """Baggage keys used for context propagation.

    Note: Identity keys use underscores instead of dots for baggage
    compatibility.
    """

    USER_ID = "identity.user_id"
    ANONYMOUS_ID = "identity.anonymous_id"
    CONVERSATION_ID = "gen_ai.conversation.id"
    PREVIOUS_RESPONSE_ID = "gen_ai.request.previous_response_id"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_ID = "gen_ai.agent.id"


@dataclass
class FeedbackProperties:
    """Feedback event properties.

    Note: trace_id, span_id, identity, gen_ai.response.id, and
    gen_ai.conversation.id are automatically extracted from the
    current OpenTelemetry span/baggage.
    """

    name: str
    """Feedback name/action (e.g., "thumbs_up", "thumbs_down", "flag")"""

    comments: str | None = None
    """User's comments (e.g., "Answer was off topic")"""

    extra: dict[str, Any] = field(default_factory=dict)
    """Additional custom data"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values.

        Returns:
            Dict with ``"name"`` always present, optional ``"comments"``,
            plus any keys from :attr:`extra` merged in.

        :attr:`extra` is seeded first so the named fields win. It used to be
        merged last, which let ``extra={"name": ...}`` silently replace the
        feedback name the event was about. Unreachable through
        ``logs.feedback(name, **extra)`` -- ``name=`` binds to the positional
        parameter -- but reachable by building this public dataclass
        directly, and the Node, browser, and Rust SDKs all settled on
        named-argument-wins for the same field.
        """
        result: dict[str, Any] = dict(self.extra)
        result["name"] = self.name
        if self.comments is not None:
            result["comments"] = self.comments
        return result
