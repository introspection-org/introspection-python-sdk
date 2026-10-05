"""OpenTelemetry-only type / constant definitions.

These were extracted from a former top-level ``types`` module
module so the REST-only install can avoid pulling them in. They cover
OTel attribute keys, baggage keys, event names, and feedback property
shapes used by :class:`~introspection_sdk.otel.logs.IntrospectionLogs`
and the span / tracing processors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "Attr",
    "Baggage",
    "DEFAULT_SERVICE_NAME",
    "EventIdentity",
    "EventName",
    "FeedbackProperties",
    "LogEventSeverity",
    "RESERVED_EVENT_NAME_PREFIXES",
    "reserved_event_name_prefix",
]

#: ``service.name`` for telemetry this SDK emits when the caller names none.
#:
#: One constant for both streams. Spans used to default to ``"introspection"``
#: while events defaulted to ``"introspection-client"``, so a single
#: :func:`~introspection_sdk.otel.init` produced two services in the backend
#: and nothing tied them together.
DEFAULT_SERVICE_NAME = "introspection-client"


#: Event-name prefixes owned by the platform (``introspection.*``) and by the
#: OpenTelemetry GenAI semantic conventions (``gen_ai.*``). A custom event
#: under either would be read as that family rather than as an app event.
RESERVED_EVENT_NAME_PREFIXES: tuple[str, ...] = ("introspection.", "gen_ai.")

#: Severity of a record emitted by ``log_event``.
LogEventSeverity = Literal["DEBUG", "INFO", "WARN", "ERROR"]


def reserved_event_name_prefix(name: str) -> str | None:
    """The reserved prefix ``name`` falls under, if any."""
    for prefix in RESERVED_EVENT_NAME_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return None


@dataclass(frozen=True)
class EventIdentity:
    """Identity known at a ``log_event`` call site.

    Each field set here replaces the one scoped on the context; a field left
    ``None`` still falls back to it.
    """

    user_id: str | None = None
    anonymous_id: str | None = None


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
        directly, and the settled spelling is
        named-argument-wins for the same field.
        """
        result: dict[str, Any] = dict(self.extra)
        result["name"] = self.name
        if self.comments is not None:
            result["comments"] = self.comments
        return result
