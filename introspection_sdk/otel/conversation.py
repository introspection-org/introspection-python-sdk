"""Centralized conversation-id generation and propagation.

One source of truth for conversation IDs: the ``conversation()`` context manager
(sets a contextvar + OTel baggage) and ``resolve_conversation_id()``, which
processors call instead of each inventing their own uuid fallback.
"""

from __future__ import annotations

import contextlib
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from contextvars import ContextVar

from opentelemetry import baggage
from opentelemetry import context as otel_context

from introspection_sdk.otel.types import Baggage

_current_conversation_id: ContextVar[str | None] = ContextVar(
    "introspection_conversation_id", default=None
)

# Stable per-trace fallback ids so spans in one trace share an id even when no
# explicit conversation() scope is active. Bounded and FIFO-evicted: a
# long-lived process sees one entry per trace, so an unbounded dict here is a
# slow leak. Traces are short-lived, so the oldest entry is also the one least
# likely to still be receiving spans.
_TRACE_FALLBACK_MAX = 4096
_trace_fallback: OrderedDict[str, str] = OrderedDict()


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
        existing = _trace_fallback.get(trace_key)
        if existing is not None:
            return existing
        cid = new_conversation_id()
        _trace_fallback[trace_key] = cid
        while len(_trace_fallback) > _TRACE_FALLBACK_MAX:
            _trace_fallback.popitem(last=False)
        return cid
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
