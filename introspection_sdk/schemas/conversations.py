"""Query-side vocabulary for the read-only ``/v1/conversations`` surface.

The response *models* live in :mod:`introspection_sdk.schemas.genai_span` —
both reads return :class:`~introspection_sdk.schemas.genai_span.GenAiSpan`.
What is left here is the vocabulary a caller sends: sort fields, the span
status and kind literals used as filters, and the remaining ``include``
expansions.

The message-family ``include`` values are gone. The items read returns the
full message history by default, so there is nothing for them to gate.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "ConversationItemInclude",
    "ConversationSortField",
    "SpanKind",
    "SpanStatus",
]

SpanStatus = Literal["Ok", "Error", "Unset"]
"""OpenTelemetry span status code values."""

SpanKind = Literal[
    "UNSPECIFIED",
    "INTERNAL",
    "SERVER",
    "CLIENT",
    "PRODUCER",
    "CONSUMER",
]
"""OpenTelemetry span kind values."""


ConversationSortField = Literal[
    "created", "duration", "turns", "tokens", "cost"
]
"""Allow-listed summary fields for ``GET /v1/conversations`` sorting."""

ConversationItemInclude = Literal[
    "events",
    "resource_attributes",
]
"""Optional conversation item expansions, passed as a repeated ``include``
query param on the items routes."""
