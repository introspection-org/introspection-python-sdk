"""Tests for centralized conversation-id generation + propagation."""

from __future__ import annotations

import introspection_sdk.otel as introspection
from introspection_sdk.otel.conversation import (
    current_conversation_id,
    new_conversation_id,
    resolve_conversation_id,
)


def test_new_id_has_prefix():
    assert new_conversation_id().startswith("intro_conv_")


def test_conversation_cm_sets_and_clears_contextvar():
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
