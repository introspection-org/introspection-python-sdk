"""Unit tests for IntrospectionConversationsSession (no API calls).

The Conversations API multi-turn flows are covered by the live integration
tests in tests/framework/test_openai_conversations.py. This file asserts the
reasoning-item stripping behaviour explicitly (Phase 3b), isolated from the
network by stubbing the parent's add_items.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("agents")

from agents.memory import OpenAIConversationsSession  # noqa: E402

from introspection_sdk.otel.sessions import (  # noqa: E402
    IntrospectionConversationsSession,
)


async def test_add_items_strips_reasoning_items(monkeypatch):
    """Reasoning items are filtered before reaching the Conversations API."""
    captured: dict[str, list] = {}

    async def fake_super_add_items(self, items):
        captured["items"] = items

    monkeypatch.setattr(
        OpenAIConversationsSession, "add_items", fake_super_add_items
    )

    session = IntrospectionConversationsSession(conversation_id="conv_test")
    items: list[Any] = [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {"type": "message", "role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    await session.add_items(items)

    forwarded = captured["items"]
    assert len(forwarded) == 2
    assert all(item.get("type") != "reasoning" for item in forwarded)


async def test_add_items_keeps_non_reasoning_items(monkeypatch):
    """A list with no reasoning items passes through unchanged."""
    captured: dict[str, list] = {}

    async def fake_super_add_items(self, items):
        captured["items"] = items

    monkeypatch.setattr(
        OpenAIConversationsSession, "add_items", fake_super_add_items
    )

    session = IntrospectionConversationsSession(conversation_id="conv_test")
    items: list[Any] = [
        {"type": "message", "role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    await session.add_items(items)

    assert captured["items"] == items
