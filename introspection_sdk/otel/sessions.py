"""Session utilities for Introspection SDK."""

from __future__ import annotations

try:
    from agents import TResponseInputItem
    from agents.memory import OpenAIConversationsSession
except ImportError as e:
    raise ImportError(
        "IntrospectionConversationsSession requires the `openai-agents` package.\n"
        "Install it with: pip install 'introspection-sdk[openai-agents]'"
    ) from e


class IntrospectionConversationsSession(OpenAIConversationsSession):
    """OpenAI Conversations session that filters out reasoning items.

    Some models (e.g. gpt-5-nano) produce reasoning items that the
    Conversations API rejects with 400 Invalid item. This session
    transparently strips them before persisting so any model works.
    """

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        filtered = [
            item
            for item in items
            if not (isinstance(item, dict) and item.get("type") == "reasoning")
        ]
        await super().add_items(filtered)
