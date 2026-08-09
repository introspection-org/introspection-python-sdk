"""Tests for centralized conversation-id generation + propagation."""

from __future__ import annotations

import introspection_sdk.otel as introspection
from introspection_sdk.otel._conversation import (
    current_conversation_id,
    new_conversation_id,
    resolve_conversation_id,
)


def test_new_id_has_prefix():
    assert new_conversation_id().startswith("intro_conv_")


def test_conversation_cm_sets_and_clears_the_scope():
    assert current_conversation_id() is None
    with introspection.conversation("conv_abc"):
        assert current_conversation_id() == "conv_abc"
        assert resolve_conversation_id() == "conv_abc"
    assert current_conversation_id() is None


def test_conversation_cm_autogenerates_when_omitted():
    with introspection.conversation() as cid:
        assert cid.startswith("intro_conv_")
        assert current_conversation_id() == cid


def test_resolve_is_stable_per_trace_key():
    a = resolve_conversation_id(trace_key="k1")
    b = resolve_conversation_id(trace_key="k1")
    assert a == b
    assert resolve_conversation_id(trace_key="k2") != a


def test_active_conversation_beats_trace_key():
    with introspection.conversation("explicit"):
        assert resolve_conversation_id(trace_key="kX") == "explicit"


def test_trace_fallback_is_bounded():
    """One entry per trace would otherwise be a slow leak in a long process."""
    # The module is `_conversation`: `otel.conversation` is the re-exported
    # context manager, which used to shadow the submodule of that name.
    from introspection_sdk.otel._conversation import (
        _TRACE_FALLBACK_MAX,
        _trace_fallback,
        resolve_conversation_id,
    )

    _trace_fallback.clear()
    first = resolve_conversation_id(trace_key="trace-0")
    for i in range(1, _TRACE_FALLBACK_MAX + 10):
        resolve_conversation_id(trace_key=f"trace-{i}")

    assert len(_trace_fallback) == _TRACE_FALLBACK_MAX
    # The oldest key was evicted, so it resolves to a fresh id.
    assert resolve_conversation_id(trace_key="trace-0") != first
    _trace_fallback.clear()


def test_trace_fallback_is_stable_across_threads():
    """`on_end` runs on whatever thread ended the span.

    Unsynchronised, two threads resolving the same trace both missed the
    lookup and both minted an id, splitting one trace across conversations.
    """
    import threading

    from introspection_sdk.otel import _conversation as conversation_mod

    def race(trace_key: str) -> set[str]:
        barrier = threading.Barrier(8)
        seen: list[str] = []
        lock = threading.Lock()

        def resolve() -> None:
            barrier.wait()
            cid = conversation_mod.resolve_conversation_id(trace_key=trace_key)
            with lock:
                seen.append(cid)

        threads = [threading.Thread(target=resolve) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return set(seen)

    for attempt in range(50):
        ids = race(f"trace-{attempt}")
        assert len(ids) == 1, f"split on attempt {attempt}: {ids}"


def test_a_conversation_scope_crosses_a_process_boundary():
    """Baggage is the copy that propagates; a contextvar never could.

    `conversation()` used to set a ContextVar alongside the baggage and
    consult it first. Injecting the context into carrier headers -- what
    happens on every outbound request -- only ever carried the baggage
    half, so the scope this function opens has to be visible there.
    """
    from opentelemetry import context as otel_context
    from opentelemetry.baggage.propagation import W3CBaggagePropagator

    carrier: dict[str, str] = {}
    with introspection.conversation("conv_xyz"):
        W3CBaggagePropagator().inject(carrier)
    assert "conv_xyz" in carrier["baggage"]

    # And it survives extraction on the far side.
    extracted = W3CBaggagePropagator().extract(carrier)
    token = otel_context.attach(extracted)
    try:
        assert resolve_conversation_id() == "conv_xyz"
    finally:
        otel_context.detach(token)
