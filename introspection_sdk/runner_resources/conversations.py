"""`runner.conversations.*` namespace: read-only conversation reads.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. The surface is
read-only and mirrors the shipped JS Runner's ``conversations`` namespace.

Two distinct paging protocols live side by side here:

* :meth:`Conversations.list` / :meth:`Conversations.iter` walk the standard
  Introspection cursor envelope's opaque ``next`` token.
* :meth:`ConversationItems.list` / :meth:`ConversationItems.iter` walk an
  OpenAI-style envelope: drive ``after = last_id`` while ``has_more`` is
  true (there is no ``next`` token).
"""

from __future__ import annotations

import builtins
from typing import Any

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    after_paginate,
    async_after_paginate,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.schemas.conversations import (
    ConversationItem,
    ConversationItemInclude,
    ConversationItemList,
    ConversationResponse,
    ConversationSummary,
)
from introspection_sdk.schemas.pagination import Paginated

#: Includes requested when building a :class:`ConversationResponse`.
RESPONSE_INCLUDES: list[ConversationItemInclude] = [
    "gen_ai.input.messages",
    "gen_ai.system_instructions",
    "gen_ai.tool.definitions",
]


def _normalize_part(part: Any) -> Any:
    """Map a legacy ``tool_call_response`` ``result`` key to ``response``.

    Older DP deployments emitted ``tool_call_response`` parts with a legacy
    ``result`` key instead of the semconv ``response`` key. Map it across so
    replayed history is always semconv-shaped. Non-tool parts and
    already-semconv parts pass through untouched.
    """
    if not isinstance(part, dict) or part.get("type") != "tool_call_response":
        return part
    if "response" in part or "result" not in part:
        return part
    rest = {k: v for k, v in part.items() if k != "result"}
    rest["response"] = part["result"]
    return rest


def _normalize_messages(messages: Any) -> Any:
    if not isinstance(messages, list):
        return messages
    out: list[Any] = []
    for msg in messages:
        if isinstance(msg, dict) and isinstance(msg.get("parts"), list):
            msg = {**msg, "parts": [_normalize_part(p) for p in msg["parts"]]}
        out.append(msg)
    return out


def _normalize_item_payload(raw: Any) -> Any:
    """Apply the legacy ``result`` -> ``response`` mapping across every
    message-bearing field of a raw conversation-item payload, before it is
    validated into the strict semconv message models."""
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    for key in (
        "input_messages",
        "output_messages",
        "gen_ai_input_messages",
        "gen_ai_output_messages",
    ):
        if key in out:
            out[key] = _normalize_messages(out[key])
    om = out.get("output_message")
    if isinstance(om, dict) and isinstance(om.get("parts"), list):
        out["output_message"] = {
            **om,
            "parts": [_normalize_part(p) for p in om["parts"]],
        }
    return out


class ConversationItems:
    """Items of a conversation (``/v1/conversations/{id}/items``). Read-only.

    Paging is OpenAI-style underneath: the envelope has no ``next`` token —
    the returned :class:`~introspection_sdk.pagination.Pager` drives
    ``after`` = the previous page's ``last_id`` while ``has_more`` is true.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        after: str | None = None,
        order: str | None = None,
        include: builtins.list[ConversationItemInclude] | None = None,
        agent_name: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        has_attribute: str | None = None,
    ) -> Pager[ConversationItem, ConversationItemList]:
        """List conversation items (OpenAI-style ``after`` / ``has_more``
        envelope). Iterate the returned :class:`Pager` to stream every item
        across pages, or call ``.page()`` for the first page only. Pass
        ``order="asc"`` to walk the transcript from the start.

        Items carry the turn-local delta in ``input_messages`` — only the
        messages new to that turn. Use :meth:`get` for the full input
        history of a span.
        """

        def fetch(cursor: str | None) -> ConversationItemList:
            params: dict[str, Any] = {
                "limit": limit,
                "after": cursor,
                "order": order,
                "include": include,
                "agent_name": agent_name,
                "service_name": service_name,
                "operation_name": operation_name,
                "has_attribute": has_attribute,
            }
            payload = self._http.request(
                "GET",
                f"/v1/conversations/{conversation_id}/items",
                params=params,
            )
            if isinstance(payload, dict) and isinstance(
                payload.get("data"), list
            ):
                payload = {
                    **payload,
                    "data": [
                        _normalize_item_payload(d) for d in payload["data"]
                    ],
                }
            return ConversationItemList.model_validate(payload)

        return after_paginate(
            fetch,
            items=lambda page: page.data,
            last_id=lambda page: page.last_id,
            has_more=lambda page: page.has_more,
            start=after,
        )

    def get(
        self,
        conversation_id: str,
        item_id: str,
        *,
        include: builtins.list[ConversationItemInclude] | None = None,
    ) -> ConversationItem:
        """Fetch a single conversation item. Unlike the list route, the
        detail's ``input_messages`` is the FULL input history for that
        span."""
        params: dict[str, Any] = {"include": include}
        payload = self._http.request(
            "GET",
            f"/v1/conversations/{conversation_id}/items/{item_id}",
            params=params,
        )
        return ConversationItem.model_validate(
            _normalize_item_payload(payload)
        )


class Conversations:
    """Read-only Conversations API (``/v1/conversations``).

    Both :meth:`list` and :meth:`items.list <ConversationItems.list>`
    return an auto-paging :class:`~introspection_sdk.pagination.Pager`, but
    they drive different wire protocols underneath: :meth:`list` walks the
    standard Introspection cursor envelope's opaque ``next`` token, while
    ``items.list`` walks an OpenAI-style envelope via ``after`` = the
    previous page's ``last_id`` while ``has_more`` is true.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http
        self.items = ConversationItems(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        model: str | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Pager[ConversationSummary, Paginated[ConversationSummary]]:
        """List conversation summaries (cursor envelope). Iterate the
        returned :class:`Pager` to stream every summary across pages, or
        call ``.page()`` for the first page only."""

        def fetch(cursor: str | None) -> Paginated[ConversationSummary]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
                "model": model,
                "agent_name": agent_name,
                "status": status,
                "service_name": service_name,
                "service_names": service_names,
                "start_date": start_date,
                "end_date": end_date,
            }
            payload = self._http.request(
                "GET", "/v1/conversations", params=params
            )
            return Paginated[ConversationSummary].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def retrieve(
        self, conversation_id: str, item_id: str | None = None
    ) -> ConversationResponse | None:
        """Responses-API-style retrieve: load the state of a conversation as
        of one item — the full input history, output, system instructions,
        and tool definitions of that turn.

        When ``item_id`` is omitted, the latest LLM turn is used: the first
        item (in descending order) whose ``node_type`` is ``"assistant"`` or
        whose ``operation_name`` is ``"chat"``, falling back to the first
        item with a non-null ``output_message``. Returns ``None`` when the
        conversation has no items.

        For the full per-turn transcript instead, iterate
        ``items.list(conversation_id, order="asc")``.
        """
        target_id = item_id or self._find_latest_turn_id(conversation_id)
        if target_id is None:
            return None

        detail = self.items.get(
            conversation_id, target_id, include=RESPONSE_INCLUDES
        )
        output_messages = detail.gen_ai_output_messages or (
            [detail.output_message] if detail.output_message else []
        )
        model = (
            detail.model_name or detail.response_model or detail.request_model
        )
        return ConversationResponse(
            conversation_id=conversation_id,
            response_id=detail.response_id,
            item_id=detail.id,
            created_at=detail.created_at,
            model=model,
            provider_name=detail.provider_name,
            # The single-item route returns the FULL input history here.
            input_messages=detail.input_messages,
            output_messages=output_messages,
            system_instructions=detail.system_instructions,
            tool_definitions=detail.tool_definitions,
        )

    def _find_latest_turn_id(self, conversation_id: str) -> str | None:
        """Scan items in descending order for the most recent LLM turn."""
        fallback: ConversationItem | None = None
        for item in self.items.list(conversation_id, order="desc"):
            if item.node_type == "assistant" or item.operation_name == "chat":
                return item.id
            if fallback is None and item.output_message is not None:
                fallback = item
        return fallback.id if fallback else None


class AsyncConversationItems:
    """Async twin of :class:`ConversationItems`. Read-only.

    Paging is OpenAI-style underneath: the envelope has no ``next`` token —
    the returned :class:`~introspection_sdk.pagination.AsyncPager` drives
    ``after`` = the previous page's ``last_id`` while ``has_more`` is true.
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        after: str | None = None,
        order: str | None = None,
        include: builtins.list[ConversationItemInclude] | None = None,
        agent_name: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        has_attribute: str | None = None,
    ) -> AsyncPager[ConversationItem, ConversationItemList]:
        """List conversation items (OpenAI-style ``after`` / ``has_more``
        envelope). ``await`` the returned :class:`AsyncPager` for the first
        page, or ``async for`` it to stream every item across pages. Pass
        ``order="asc"`` to walk the transcript from the start.

        Items carry the turn-local delta in ``input_messages`` — only the
        messages new to that turn. Use :meth:`get` for the full input
        history of a span.
        """

        async def fetch(cursor: str | None) -> ConversationItemList:
            params: dict[str, Any] = {
                "limit": limit,
                "after": cursor,
                "order": order,
                "include": include,
                "agent_name": agent_name,
                "service_name": service_name,
                "operation_name": operation_name,
                "has_attribute": has_attribute,
            }
            payload = await self._http.request(
                "GET",
                f"/v1/conversations/{conversation_id}/items",
                params=params,
            )
            if isinstance(payload, dict) and isinstance(
                payload.get("data"), list
            ):
                payload = {
                    **payload,
                    "data": [
                        _normalize_item_payload(d) for d in payload["data"]
                    ],
                }
            return ConversationItemList.model_validate(payload)

        return async_after_paginate(
            fetch,
            items=lambda page: page.data,
            last_id=lambda page: page.last_id,
            has_more=lambda page: page.has_more,
            start=after,
        )

    async def get(
        self,
        conversation_id: str,
        item_id: str,
        *,
        include: builtins.list[ConversationItemInclude] | None = None,
    ) -> ConversationItem:
        """Fetch a single conversation item. Unlike the list route, the
        detail's ``input_messages`` is the FULL input history for that
        span."""
        params: dict[str, Any] = {"include": include}
        payload = await self._http.request(
            "GET",
            f"/v1/conversations/{conversation_id}/items/{item_id}",
            params=params,
        )
        return ConversationItem.model_validate(
            _normalize_item_payload(payload)
        )


class AsyncConversations:
    """Async twin of :class:`Conversations`. Read-only
    (``/v1/conversations``).

    Both :meth:`list` and :meth:`items.list <AsyncConversationItems.list>`
    return an auto-paging :class:`~introspection_sdk.pagination.AsyncPager`,
    but they drive different wire protocols underneath: :meth:`list` walks
    the standard Introspection cursor envelope's opaque ``next`` token,
    while ``items.list`` walks an OpenAI-style envelope via ``after`` = the
    previous page's ``last_id`` while ``has_more`` is true.
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self.items = AsyncConversationItems(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        model: str | None = None,
        agent_name: str | None = None,
        status: str | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> AsyncPager[ConversationSummary, Paginated[ConversationSummary]]:
        """List conversation summaries (cursor envelope). ``await`` the
        returned :class:`AsyncPager` for the first page, or ``async for`` it
        to stream every summary across pages."""

        async def fetch(
            cursor: str | None,
        ) -> Paginated[ConversationSummary]:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include_total": include_total,
                "model": model,
                "agent_name": agent_name,
                "status": status,
                "service_name": service_name,
                "service_names": service_names,
                "start_date": start_date,
                "end_date": end_date,
            }
            payload = await self._http.request(
                "GET", "/v1/conversations", params=params
            )
            return Paginated[ConversationSummary].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    async def retrieve(
        self, conversation_id: str, item_id: str | None = None
    ) -> ConversationResponse | None:
        """Responses-API-style retrieve: load the state of a conversation as
        of one item — the full input history, output, system instructions,
        and tool definitions of that turn.

        When ``item_id`` is omitted, the latest LLM turn is used: the first
        item (in descending order) whose ``node_type`` is ``"assistant"`` or
        whose ``operation_name`` is ``"chat"``, falling back to the first
        item with a non-null ``output_message``. Returns ``None`` when the
        conversation has no items.

        For the full per-turn transcript instead, iterate
        ``items.list(conversation_id, order="asc")``.
        """
        target_id = item_id or await self._find_latest_turn_id(conversation_id)
        if target_id is None:
            return None

        detail = await self.items.get(
            conversation_id, target_id, include=RESPONSE_INCLUDES
        )
        output_messages = detail.gen_ai_output_messages or (
            [detail.output_message] if detail.output_message else []
        )
        model = (
            detail.model_name or detail.response_model or detail.request_model
        )
        return ConversationResponse(
            conversation_id=conversation_id,
            response_id=detail.response_id,
            item_id=detail.id,
            created_at=detail.created_at,
            model=model,
            provider_name=detail.provider_name,
            # The single-item route returns the FULL input history here.
            input_messages=detail.input_messages,
            output_messages=output_messages,
            system_instructions=detail.system_instructions,
            tool_definitions=detail.tool_definitions,
        )

    async def _find_latest_turn_id(self, conversation_id: str) -> str | None:
        """Scan items in descending order for the most recent LLM turn."""
        fallback: ConversationItem | None = None
        async for item in self.items.list(conversation_id, order="desc"):
            if item.node_type == "assistant" or item.operation_name == "chat":
                return item.id
            if fallback is None and item.output_message is not None:
                fallback = item
        return fallback.id if fallback else None
