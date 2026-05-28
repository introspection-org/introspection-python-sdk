"""Centralized conversation-id generation and propagation.

One source of truth for conversation IDs: the ``conversation()`` context manager
(sets a contextvar + OTel baggage) and ``resolve_conversation_id()``, which
processors call instead of each inventing their own uuid fallback.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar

from opentelemetry import baggage
from opentelemetry import context as otel_context

from introspection_sdk.otel.types import Baggage

_current_conversation_id: ContextVar[str | None] = ContextVar(
    "introspection_conversation_id", default=None
)

# Stable per-trace fallback ids so spans in one trace share an id even when no
# explicit conversation() scope is active.
_trace_fallback: dict[str, str] = {}


def new_conversation_id() -> str:
    return f"intro_conv_{uuid.uuid4().hex}"


def current_conversation_id() -> str | None:
    return _current_conversation_id.get()


def resolve_conversation_id(*, trace_key: str | None = None) -> str:
    """Resolve the conversation id to stamp on a span.

    Precedence: active ``conversation()`` scope > OTel baggage > stable
    per-``trace_key`` fallback > a fresh id.
    """
    cid = _current_conversation_id.get()
    if cid:
        return cid

    from_baggage = baggage.get_baggage(Baggage.CONVERSATION_ID)
    if isinstance(from_baggage, str) and from_baggage:
        return from_baggage

    if trace_key is not None:
        return _trace_fallback.setdefault(trace_key, new_conversation_id())
    return new_conversation_id()


@contextlib.contextmanager
def conversation(conversation_id: str | None = None) -> Iterator[str]:
    """Scope a conversation: set the contextvar + OTel baggage; yield the id."""
    cid = conversation_id or new_conversation_id()
    token = _current_conversation_id.set(cid)
    otel_token = otel_context.attach(
        baggage.set_baggage(Baggage.CONVERSATION_ID, cid)
    )
    try:
        yield cid
    finally:
        otel_context.detach(otel_token)
        _current_conversation_id.reset(token)
