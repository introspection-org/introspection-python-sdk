"""Classify caller-initiated aborts on gen_ai spans (mirrors the JS SDK).

When a caller cancels an in-flight LLM call — an ``asyncio`` task cancel, a
Ctrl-C, or breaking out of a stream early — the OTel span should read as a
deliberate stop, not a failure. OTel status has only ``Unset``/``Ok``/``Error``
(there is no "cancelled" code), so we leave the status **Unset** and annotate
the span with the native ``gen_ai.response.finish_reasons=["aborted"]`` plus the
namespaced ``introspection.termination_reason="cancelled"`` attribute the
platform's read layer keys on to exclude these spans from error counts. This is
the same shape the JS SDK emits, so both are treated identically downstream.

All three cancellation signals are ``BaseException`` subclasses, so they escape
``except Exception`` and never reach the ERROR path on their own; the wrappers
add an explicit ``except CANCELLATION_EXCEPTIONS`` clause to annotate the span
before re-raising.
"""

from __future__ import annotations

import asyncio

from opentelemetry.trace import Span

__all__ = [
    "CANCELLATION_EXCEPTIONS",
    "FINISH_REASON_ABORTED",
    "TERMINATION_REASON_CANCELLED",
    "mark_span_cancelled",
]

#: Native gen_ai finish reason recorded for a caller-aborted call. Matches the
#: JS SDK so the platform read layer treats both identically.
FINISH_REASON_ABORTED = "aborted"

#: Value of the namespaced ``introspection.termination_reason`` attribute.
TERMINATION_REASON_CANCELLED = "cancelled"

#: Signals that mean "the caller stopped this", not "it failed": async task
#: cancellation, Ctrl-C / SIGINT, and closing a stream generator early. All are
#: ``BaseException`` subclasses, so they never hit an ``except Exception``.
CANCELLATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    GeneratorExit,
)


def mark_span_cancelled(span: Span) -> None:
    """Annotate ``span`` as a caller-cancelled call, leaving its status Unset.

    Idempotent and safe on an already-ended span: a non-recording span is left
    untouched. Records no exception — a cancellation is not an error.
    """
    if not span.is_recording():
        return
    span.set_attribute(
        "gen_ai.response.finish_reasons", [FINISH_REASON_ABORTED]
    )
    span.set_attribute(
        "introspection.termination_reason", TERMINATION_REASON_CANCELLED
    )
