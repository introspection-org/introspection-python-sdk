"""`runner.conversations.*` namespace: read-only conversation reads.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. The surface is
read-only and mirrors the shipped JS Runner's ``conversations`` namespace.

Both conversation summaries and conversation items walk opaque ``next``
cursors. The item envelope retains OpenAI-style ``first_id`` / ``last_id``
metadata, but those identifiers do not drive pagination.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from typing import Any, Literal, TypedDict, Unpack
from urllib.parse import quote
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk._http import RawResponse, _AsyncHttpClient, _HttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    Pager,
    async_cursor_paginate,
    cursor_paginate,
)
from introspection_sdk.runner_resources._reads import (
    ARROW_ACCEPT_HEADERS,
    TRAJECTORY_ACCEPT_HEADERS,
    ArrowPageIterator,
    AsyncArrowPageIterator,
    ReadFormat,
    decode_arrow_page,
    decode_arrow_table,
    resolve_window,
)
from introspection_sdk.schemas.conversations import (
    Conversation,
    ConversationItemInclude,
    ConversationSortField,
    SpanStatus,
)
from introspection_sdk.schemas.genai_span import GenAiSpan, GenAiSpanList
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.trajectory import Trajectory, TrajectoryRecord

#: Validates a decoded export body into the trajectory-v1 record array.
TRAJECTORY_ADAPTER: TypeAdapter[list[TrajectoryRecord]] = TypeAdapter(
    list[TrajectoryRecord]
)

ConversationExportFormat = Literal["json", "trajectory", "arrow"]
"""Wire representation accepted by the complete conversation export route."""


class ConversationExportParams(TypedDict, total=False):
    """Filters accepted by the complete conversation export route."""

    agent: str
    service_name: str
    operation_name: str
    lookback_days: int
    share_id: str | UUID
    start_date: str | datetime
    end_date: str | datetime


JSON_EXPORT_HEADERS = {"Accept": "application/json"}


def build_export_params(
    *,
    agent: str | None = None,
    service_name: str | None = None,
    operation_name: str | None = None,
    lookback_days: int | None = None,
    share_id: str | UUID | None = None,
    start_date: str | datetime | None = None,
    end_date: str | datetime | None = None,
) -> dict[str, Any]:
    """Query params for the conversation export route.

    The export is assembled server-side over the whole conversation, so
    there is no cursor or page bound here: every param filters what gets
    assembled.

    ``start_date`` / ``end_date`` bound which records are assembled. Unlike
    the list routes, this route takes them under their wire names with no
    ergonomic ``start`` / ``end`` / ``lookback`` aliases, because the route's
    own relative window is the separate ``lookback_days`` integer.
    """
    params: dict[str, Any] = {}
    if agent is not None:
        params["agent"] = agent
    if service_name is not None:
        params["service_name"] = service_name
    if operation_name is not None:
        params["operation_name"] = operation_name
    if lookback_days is not None:
        params["lookback_days"] = lookback_days
    if share_id is not None:
        params["share_id"] = str(share_id)
    if start_date is not None:
        params["start_date"] = start_date
    if end_date is not None:
        params["end_date"] = end_date
    return params


def _export_path(conversation_id: str) -> str:
    return f"/v1/conversations/{quote(conversation_id, safe='')}/export"


def _export_headers(format: ConversationExportFormat) -> dict[str, str]:
    if format == "trajectory":
        return TRAJECTORY_ACCEPT_HEADERS
    if format == "arrow":
        return ARROW_ACCEPT_HEADERS
    return JSON_EXPORT_HEADERS


def build_conversation_params(
    *,
    limit: int = 100,
    cursor: str | None = None,
    conversation_id: str | None = None,
    sort: ConversationSortField | None = None,
    direction: Literal["asc", "desc"] | None = None,
    model: str | None = None,
    agent_name: str | None = None,
    status: SpanStatus | None = None,
    service_name: str | None = None,
    service_names: builtins.list[str] | None = None,
    environment: str | None = None,
    runtime_id: UUID | None = None,
    runtime_group_id: UUID | None = None,
    experiment_id: UUID | None = None,
    recipe_git_commit_sha: str | None = None,
    start_date: str | datetime | None = None,
    end_date: str | datetime | None = None,
) -> dict[str, Any]:
    """Fold the shared conversations list/arrow kwargs into query params."""
    return {
        "limit": limit,
        "next": cursor,
        "conversation_id": conversation_id,
        "sort": sort,
        "direction": direction,
        "model": model,
        "agent_name": agent_name,
        "status": status,
        "service_name": service_name,
        "service_names": service_names,
        "environment": environment,
        "runtime_id": runtime_id,
        "runtime_group_id": runtime_group_id,
        "experiment_id": experiment_id,
        "recipe_git_commit_sha": recipe_git_commit_sha,
        "start_date": start_date,
        "end_date": end_date,
    }


# The message-family `include` values are gone: the items read returns the
# full history by default, so there is nothing left for them to gate. Asking
# for context you already have was the old shape's sharpest edge — forget the
# parameter and you silently forked a conversation with one turn of context.


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
    """Apply the legacy ``result`` -> ``response`` mapping to a span payload.

    The mapping itself is unchanged and still needed — it is a compatibility
    shim for older DP deployments, not an artifact of the old envelope. What
    changed is where the messages live: they used to be flat top-level fields,
    and now they sit at ``attributes.gen_ai.input.messages`` /
    ``attributes.gen_ai.output.messages``, so the walk follows the tree.
    """
    if not isinstance(raw, dict):
        return raw
    attributes = raw.get("attributes")
    if not isinstance(attributes, dict):
        return raw
    gen_ai = attributes.get("gen_ai")
    if not isinstance(gen_ai, dict):
        return raw

    patched_gen_ai = dict(gen_ai)
    for key in ("input", "output"):
        node = patched_gen_ai.get(key)
        if isinstance(node, dict) and "messages" in node:
            patched_gen_ai[key] = {
                **node,
                "messages": _normalize_messages(node["messages"]),
            }
    return {
        **raw,
        "attributes": {**attributes, "gen_ai": patched_gen_ai},
    }


def _conversation_items_next(page: GenAiSpanList) -> str | None:
    if page.has_more and page.next is None:
        raise ValueError("conversation items page has_more without next")
    return page.next


class ConversationItems:
    """Items of a conversation (``/v1/conversations/{id}/items``). Read-only.

    The returned :class:`~introspection_sdk.pagination.Pager` passes each
    page's opaque ``next`` token back unchanged.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http

    def list(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include: builtins.list[ConversationItemInclude] | None = None,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lookback_days: int | None = None,
        share_id: str | None = None,
    ) -> Pager[GenAiSpan, GenAiSpanList]:
        """List conversation items using an opaque ``next`` cursor. Iterate
        the returned :class:`Pager` to stream every item
        across pages, or call ``.page()`` for the first page only.

        Items are always returned newest-first: the route hardcodes a
        descending sort and rejects a cursor that disagrees, so there is no
        ordering parameter.

        Items carry the turn-local delta in ``input_messages`` — only the
        messages new to that turn. Use :meth:`get` for the full input
        history of a span.
        """

        def fetch(cursor: str | None) -> GenAiSpanList:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include": include,
                "agent": agent,
                "service_name": service_name,
                "operation_name": operation_name,
                "start_date": start_date,
                "end_date": end_date,
                "lookback_days": lookback_days,
                "share_id": share_id,
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
            return GenAiSpanList.model_validate(payload)

        return Pager(
            fetch,
            items=lambda page: page.data,
            next_cursor=_conversation_items_next,
            start=next,
        )

    def get(
        self,
        conversation_id: str,
        item_id: str,
        *,
        include: builtins.list[ConversationItemInclude] | None = None,
    ) -> GenAiSpan:
        """Fetch a single conversation item. Unlike the list route, the
        detail's ``input_messages`` is the FULL input history for that
        span."""
        params: dict[str, Any] = {"include": include}
        payload = self._http.request(
            "GET",
            f"/v1/conversations/{conversation_id}/items/{item_id}",
            params=params,
        )
        return GenAiSpan.model_validate(_normalize_item_payload(payload))


class Conversations:
    """Read-only Conversations API (``/v1/conversations``).

    Both :meth:`list` and :meth:`items.list <ConversationItems.list>`
    return an auto-paging :class:`~introspection_sdk.pagination.Pager` and
    pass each page's opaque ``next`` token back unchanged.
    """

    def __init__(self, http: _HttpClient) -> None:
        self._http = http
        self.items = ConversationItems(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        format: ReadFormat = "json",
    ) -> Pager[Conversation, Paginated[Conversation]]:
        """List conversation summaries (cursor envelope). Iterate the
        returned :class:`Pager` to stream every summary across pages, or
        call ``.page()`` for the first page only.

        ``order`` is an alias for ``direction``; ``start`` / ``end`` for
        ``start_date`` / ``end_date``; ``lookback`` (e.g. ``"24h"``) sets
        ``start_date = now - lookback`` and is mutually exclusive with
        ``start`` / ``end``. ``format="arrow"`` negotiates the columnar Arrow
        stream, decoded back into the same envelope."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )

        def fetch(cursor: str | None) -> Paginated[Conversation]:
            params = build_conversation_params(
                limit=limit,
                cursor=cursor,
                conversation_id=conversation_id,
                sort=sort,
                direction=direction or order,
                model=model,
                agent_name=agent_name,
                status=status,
                service_name=service_name,
                service_names=service_names,
                environment=environment,
                runtime_id=runtime_id,
                runtime_group_id=runtime_group_id,
                experiment_id=experiment_id,
                recipe_git_commit_sha=recipe_git_commit_sha,
                start_date=resolved_start,
                end_date=resolved_end,
            )
            if format == "arrow":
                raw = self._http.request(
                    "GET",
                    "/v1/conversations",
                    params=params,
                    headers=ARROW_ACCEPT_HEADERS,
                    expect="raw",
                )
                assert isinstance(raw, RawResponse)
                return decode_arrow_page(raw, Conversation.model_validate)
            payload = self._http.request(
                "GET", "/v1/conversations", params=params
            )
            return Paginated[Conversation].model_validate(payload)

        return cursor_paginate(fetch, start=next)

    def list_arrow(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
    ) -> ArrowPageIterator:
        """Columnar accessor: iterate one ``pyarrow.Table`` per server page
        (constant memory), or call ``.read_all()`` to concatenate every
        page into one Table. Same filters as :meth:`list`; requires the
        ``[arrow]`` extra."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )

        def fetch(cursor: str | None) -> RawResponse:
            params = build_conversation_params(
                limit=limit,
                cursor=cursor,
                conversation_id=conversation_id,
                sort=sort,
                direction=direction or order,
                model=model,
                agent_name=agent_name,
                status=status,
                service_name=service_name,
                service_names=service_names,
                environment=environment,
                runtime_id=runtime_id,
                runtime_group_id=runtime_group_id,
                experiment_id=experiment_id,
                recipe_git_commit_sha=recipe_git_commit_sha,
                start_date=resolved_start,
                end_date=resolved_end,
            )
            raw = self._http.request(
                "GET",
                "/v1/conversations",
                params=params,
                headers=ARROW_ACCEPT_HEADERS,
                expect="raw",
            )
            assert isinstance(raw, RawResponse)
            return raw

        return ArrowPageIterator(fetch, start=next)

    def iterate(
        self,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> Iterator[Conversation]:
        """Cursor generator: page through :meth:`list` to exhaustion, yielding
        every summary. ``max_items`` bounds the total yielded (``None`` = no
        bound). All other keyword args are forwarded to :meth:`list`."""
        if max_items is not None and max_items <= 0:
            return
        yielded = 0
        for record in self.list(**kwargs):
            yield record
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return

    def get(self, conversation_id: str) -> Conversation:
        """Fetch one conversation summary with its complete agent index."""
        payload = self._http.request(
            "GET", f"/v1/conversations/{conversation_id}"
        )
        return Conversation.model_validate(payload)

    def export_json(
        self,
        conversation_id: str,
        **params: Unpack[ConversationExportParams],
    ) -> GenAiSpanList:
        """Export one complete conversation as the standard GenAI-span list."""
        payload = self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(**params),
            headers=JSON_EXPORT_HEADERS,
        )
        return GenAiSpanList.model_validate(payload)

    def export_stream(
        self,
        conversation_id: str,
        format: ConversationExportFormat,
        **params: Unpack[ConversationExportParams],
    ) -> Iterator[bytes]:
        """Stream raw complete-export bytes without buffering them in the SDK."""
        return self._http.stream_bytes(
            _export_path(conversation_id),
            params=build_export_params(**params),
            headers=_export_headers(format),
        )

    def export_trajectory(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Trajectory:
        """Export one complete conversation as trajectory-v1.

        This is not :meth:`ConversationItems.list` in another coat. The
        export is assembled server-side over the whole conversation, so it
        carries no cursor and no page bound; the keyword args filter what
        gets assembled.

        The trajectory is a projection derived on read from the stored
        GenAI messages, so a conversation that cannot be represented as
        trajectory-v1 raises rather than returning a partial export, and a
        conversation with no exportable records raises ``NotFoundError``.
        """
        payload = self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(
                agent=agent,
                service_name=service_name,
                operation_name=operation_name,
                lookback_days=lookback_days,
                share_id=share_id,
                start_date=start_date,
                end_date=end_date,
            ),
            headers=TRAJECTORY_ACCEPT_HEADERS,
        )
        return TRAJECTORY_ADAPTER.validate_python(payload)

    def export_arrow(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Any:
        """Export one complete conversation as a single ``pyarrow.Table``.

        Unlike :meth:`list_arrow`, this is one table for the whole conversation
        rather than an iterator of pages: the export route assembles the
        conversation server-side and streams it in one response. Returns
        ``None`` for an empty body.

        Requires the optional ``pyarrow`` dependency.
        """
        raw = self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(
                agent=agent,
                service_name=service_name,
                operation_name=operation_name,
                lookback_days=lookback_days,
                share_id=share_id,
                start_date=start_date,
                end_date=end_date,
            ),
            headers=ARROW_ACCEPT_HEADERS,
            expect="raw",
        )
        assert isinstance(raw, RawResponse)
        return decode_arrow_table(raw)

    def retrieve(
        self, conversation_id: str, item_id: str | None = None
    ) -> GenAiSpan | None:
        """Load the state of a conversation as of one item.

        Returns the span itself. There is no separate response type any more:
        the items read already carries the full input history, system
        instructions, and tool definitions, so composing a second object from
        it would just be copying fields into different names.

        When ``item_id`` is omitted the latest LLM turn is used — the first
        item in descending order whose ``gen_ai.operation.name`` is
        ``"chat"``, falling back to the first item that produced any output.
        Returns ``None`` when the conversation has no items.

        For the full per-turn transcript instead, iterate
        ``items.list(conversation_id)``, which is newest-first.
        """
        target_id = item_id or self._find_latest_turn_id(conversation_id)
        if target_id is None:
            return None
        return self.items.get(conversation_id, target_id)

    def _find_latest_turn_id(self, conversation_id: str) -> str | None:
        """Scan items in descending order for the most recent LLM turn.

        The old heuristic also matched ``node_type == "assistant"``, but
        ``node_type`` was a precomputed UI tree hint with no semantic-convention
        equivalent and is gone from the wire. ``gen_ai.operation.name`` is the
        attribute that actually carried the meaning.
        """
        fallback: GenAiSpan | None = None
        # The route is descending-only, so the first match is the latest.
        for item in self.items.list(conversation_id):
            gen_ai = item.attributes.gen_ai
            operation = (
                gen_ai.operation.name if gen_ai and gen_ai.operation else None
            )
            if operation == "chat":
                return item.span_id
            if fallback is None and item.output_messages:
                fallback = item
        return fallback.span_id if fallback else None


class AsyncConversationItems:
    """Async twin of :class:`ConversationItems`. Read-only.

    The returned :class:`~introspection_sdk.pagination.AsyncPager` passes each
    page's opaque ``next`` token back unchanged.
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http

    def list(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include: builtins.list[ConversationItemInclude] | None = None,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lookback_days: int | None = None,
        share_id: str | None = None,
    ) -> AsyncPager[GenAiSpan, GenAiSpanList]:
        """List conversation items using an opaque ``next`` cursor. ``await``
        the returned :class:`AsyncPager` for the first
        page, or ``async for`` it to stream every item across pages.

        Items are always returned newest-first: the route hardcodes a
        descending sort and rejects a cursor that disagrees, so there is no
        ordering parameter.

        Items carry the turn-local delta in ``input_messages`` — only the
        messages new to that turn. Use :meth:`get` for the full input
        history of a span.
        """

        async def fetch(cursor: str | None) -> GenAiSpanList:
            params: dict[str, Any] = {
                "limit": limit,
                "next": cursor,
                "include": include,
                "agent": agent,
                "service_name": service_name,
                "operation_name": operation_name,
                "start_date": start_date,
                "end_date": end_date,
                "lookback_days": lookback_days,
                "share_id": share_id,
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
            return GenAiSpanList.model_validate(payload)

        return AsyncPager(
            fetch,
            items=lambda page: page.data,
            next_cursor=_conversation_items_next,
            start=next,
        )

    async def get(
        self,
        conversation_id: str,
        item_id: str,
        *,
        include: builtins.list[ConversationItemInclude] | None = None,
    ) -> GenAiSpan:
        """Fetch a single conversation item. Unlike the list route, the
        detail's ``input_messages`` is the FULL input history for that
        span."""
        params: dict[str, Any] = {"include": include}
        payload = await self._http.request(
            "GET",
            f"/v1/conversations/{conversation_id}/items/{item_id}",
            params=params,
        )
        return GenAiSpan.model_validate(_normalize_item_payload(payload))


class AsyncConversations:
    """Async twin of :class:`Conversations`. Read-only
    (``/v1/conversations``).

    Both :meth:`list` and :meth:`items.list <AsyncConversationItems.list>`
    return an auto-paging :class:`~introspection_sdk.pagination.AsyncPager`
    and pass each page's opaque ``next`` token back unchanged.
    """

    def __init__(self, http: _AsyncHttpClient) -> None:
        self._http = http
        self.items = AsyncConversationItems(http)

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        format: ReadFormat = "json",
    ) -> AsyncPager[Conversation, Paginated[Conversation]]:
        """List conversation summaries (cursor envelope). ``await`` the
        returned :class:`AsyncPager` for the first page, or ``async for`` it
        to stream every summary across pages. See
        :meth:`Conversations.list` for the param semantics."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )

        async def fetch(
            cursor: str | None,
        ) -> Paginated[Conversation]:
            params = build_conversation_params(
                limit=limit,
                cursor=cursor,
                conversation_id=conversation_id,
                sort=sort,
                direction=direction or order,
                model=model,
                agent_name=agent_name,
                status=status,
                service_name=service_name,
                service_names=service_names,
                environment=environment,
                runtime_id=runtime_id,
                runtime_group_id=runtime_group_id,
                experiment_id=experiment_id,
                recipe_git_commit_sha=recipe_git_commit_sha,
                start_date=resolved_start,
                end_date=resolved_end,
            )
            if format == "arrow":
                raw = await self._http.request(
                    "GET",
                    "/v1/conversations",
                    params=params,
                    headers=ARROW_ACCEPT_HEADERS,
                    expect="raw",
                )
                assert isinstance(raw, RawResponse)
                return decode_arrow_page(raw, Conversation.model_validate)
            payload = await self._http.request(
                "GET", "/v1/conversations", params=params
            )
            return Paginated[Conversation].model_validate(payload)

        return async_cursor_paginate(fetch, start=next)

    def list_arrow(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
    ) -> AsyncArrowPageIterator:
        """Columnar accessor: ``async for`` one ``pyarrow.Table`` per server
        page, or ``await .read_all()`` to concatenate every page into one
        Table. Same filters as :meth:`list`; requires the ``[arrow]``
        extra."""
        resolved_start, resolved_end = resolve_window(
            start=start,
            end=end,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
        )

        async def fetch(cursor: str | None) -> RawResponse:
            params = build_conversation_params(
                limit=limit,
                cursor=cursor,
                conversation_id=conversation_id,
                sort=sort,
                direction=direction or order,
                model=model,
                agent_name=agent_name,
                status=status,
                service_name=service_name,
                service_names=service_names,
                environment=environment,
                runtime_id=runtime_id,
                runtime_group_id=runtime_group_id,
                experiment_id=experiment_id,
                recipe_git_commit_sha=recipe_git_commit_sha,
                start_date=resolved_start,
                end_date=resolved_end,
            )
            raw = await self._http.request(
                "GET",
                "/v1/conversations",
                params=params,
                headers=ARROW_ACCEPT_HEADERS,
                expect="raw",
            )
            assert isinstance(raw, RawResponse)
            return raw

        return AsyncArrowPageIterator(fetch, start=next)

    async def iterate(
        self,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Conversation]:
        """Cursor generator: page through :meth:`list` to exhaustion, yielding
        every summary. ``max_items`` bounds the total yielded (``None`` = no
        bound). All other keyword args are forwarded to :meth:`list`."""
        if max_items is not None and max_items <= 0:
            return
        yielded = 0
        async for record in self.list(**kwargs):
            yield record
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return

    async def get(self, conversation_id: str) -> Conversation:
        """Fetch one conversation summary with its complete agent index."""
        payload = await self._http.request(
            "GET", f"/v1/conversations/{conversation_id}"
        )
        return Conversation.model_validate(payload)

    async def export_json(
        self,
        conversation_id: str,
        **params: Unpack[ConversationExportParams],
    ) -> GenAiSpanList:
        """Async twin of :meth:`Conversations.export_json`."""
        payload = await self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(**params),
            headers=JSON_EXPORT_HEADERS,
        )
        return GenAiSpanList.model_validate(payload)

    def export_stream(
        self,
        conversation_id: str,
        format: ConversationExportFormat,
        **params: Unpack[ConversationExportParams],
    ) -> AsyncIterator[bytes]:
        """Async byte-stream twin of :meth:`Conversations.export_stream`."""
        return self._http.stream_bytes(
            _export_path(conversation_id),
            params=build_export_params(**params),
            headers=_export_headers(format),
        )

    async def export_trajectory(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Trajectory:
        """Async twin of :meth:`Conversations.export_trajectory`."""
        payload = await self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(
                agent=agent,
                service_name=service_name,
                operation_name=operation_name,
                lookback_days=lookback_days,
                share_id=share_id,
                start_date=start_date,
                end_date=end_date,
            ),
            headers=TRAJECTORY_ACCEPT_HEADERS,
        )
        return TRAJECTORY_ADAPTER.validate_python(payload)

    async def export_arrow(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Any:
        """Async twin of :meth:`Conversations.export_arrow`."""
        raw = await self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(
                agent=agent,
                service_name=service_name,
                operation_name=operation_name,
                lookback_days=lookback_days,
                share_id=share_id,
                start_date=start_date,
                end_date=end_date,
            ),
            headers=ARROW_ACCEPT_HEADERS,
            expect="raw",
        )
        assert isinstance(raw, RawResponse)
        return decode_arrow_table(raw)

    async def retrieve(
        self, conversation_id: str, item_id: str | None = None
    ) -> GenAiSpan | None:
        """Load the state of a conversation as of one item.

        Returns the span itself. There is no separate response type any more:
        the items read already carries the full input history, system
        instructions, and tool definitions, so composing a second object from
        it would just be copying fields into different names.

        When ``item_id`` is omitted the latest LLM turn is used — the first
        item in descending order whose ``gen_ai.operation.name`` is
        ``"chat"``, falling back to the first item that produced any output.
        Returns ``None`` when the conversation has no items.

        For the full per-turn transcript instead, iterate
        ``items.list(conversation_id)``, which is newest-first.
        """
        target_id = item_id or await self._find_latest_turn_id(conversation_id)
        if target_id is None:
            return None
        return await self.items.get(conversation_id, target_id)

    async def _find_latest_turn_id(self, conversation_id: str) -> str | None:
        """Scan items in descending order for the most recent LLM turn.

        The old heuristic also matched ``node_type == "assistant"``, but
        ``node_type`` was a precomputed UI tree hint with no semantic-convention
        equivalent and is gone from the wire. ``gen_ai.operation.name`` is the
        attribute that actually carried the meaning.
        """
        fallback: GenAiSpan | None = None
        # The route is descending-only, so the first match is the latest.
        async for item in self.items.list(conversation_id):
            gen_ai = item.attributes.gen_ai
            operation = (
                gen_ai.operation.name if gen_ai and gen_ai.operation else None
            )
            if operation == "chat":
                return item.span_id
            if fallback is None and item.output_messages:
                fallback = item
        return fallback.span_id if fallback else None
