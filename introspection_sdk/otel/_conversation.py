"""Centralized conversation-id generation and propagation.

One source of truth for conversation IDs: the ``conversation()`` context
manager (which scopes the id on OTel baggage) and
``resolve_conversation_id()``, which processors call instead of each
inventing their own uuid fallback.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterator

from opentelemetry import baggage
from opentelemetry import context as otel_context

from introspection_sdk.otel.types import Baggage

# Stable per-trace fallback ids so spans in one trace share an id even when no
# explicit conversation() scope is active. Bounded and FIFO-evicted: a
# long-lived process sees one entry per trace, so an unbounded dict here is a
# slow leak. Traces are short-lived, so the oldest entry is also the one least
# likely to still be receiving spans.
_TRACE_FALLBACK_MAX = 4096
_trace_fallback: OrderedDict[str, str] = OrderedDict()
# `on_end` runs on whatever thread ended the span. Without this, two threads
# resolving the same trace both missed the lookup and both minted an id, so a
# single trace reached the UI split across several conversations.
_trace_fallback_lock = threading.Lock()


def new_conversation_id() -> str:
    return f"intro_conv_{uuid.uuid4().hex}"


def current_conversation_id() -> str | None:
    """The conversation scoped on the current context, if any."""
    value = baggage.get_baggage(Baggage.CONVERSATION_ID)
    return value if isinstance(value, str) and value else None


def resolve_conversation_id(*, trace_key: str | None = None) -> str:
    """Resolve the conversation id to stamp on a span.

    Precedence: OTel baggage (which is what ``conversation()`` sets) >
    stable per-``trace_key`` fallback > a fresh id. The same precedence the
    backend expects.
    """
    from_baggage = baggage.get_baggage(Baggage.CONVERSATION_ID)
    if isinstance(from_baggage, str) and from_baggage:
        return from_baggage

    if trace_key is not None:
        with _trace_fallback_lock:
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
    """Scope a conversation on the OTel baggage; yield the id.

    Baggage is the whole mechanism. There used to be a ``ContextVar``
    carried alongside it and consulted first, but the two were set and
    cleared together by this one function and nothing else could write
    either, so it was a second copy of the same fact -- and one the JS and
    other entry points do not have. Baggage is also the copy that crosses a process
    boundary, which the contextvar never could.
    """
    cid = conversation_id or new_conversation_id()
    token = otel_context.attach(
        baggage.set_baggage(Baggage.CONVERSATION_ID, cid)
    )
    try:
        yield cid
    finally:
        otel_context.detach(token)
