"""Async twins re-exported by :mod:`introspection_sdk.runner_resources.conversations`."""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal, Unpack
from uuid import UUID

from introspection_sdk._http import RawResponse, _AsyncHttpClient
from introspection_sdk.pagination import (
    AsyncPager,
    async_cursor_paginate,
)
from introspection_sdk.runner_resources._conversations_common import (
    JSON_EXPORT_HEADERS,
    LATEST_TURN_SCAN_LIMIT,
    TRAJECTORY_ADAPTER,
    ConversationExportFormat,
    ConversationExportParams,
    ConversationResolution,
    ConversationSentiment,
    _conversation_items_next,
    _export_headers,
    _export_path,
    _normalize_item_payload,
    build_conversation_params,
    build_export_params,
)
from introspection_sdk.runner_resources._reads import (
    ARROW_ACCEPT_HEADERS,
    TRAJECTORY_ACCEPT_HEADERS,
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
from introspection_sdk.schemas.trajectory import Trajectory


class AsyncConversationItems:
    # unasync: async-only (the sync twin's docstring follows)
    """Async twin of :class:`ConversationItems`. Read-only.

    The returned :class:`~introspection_sdk.pagination.AsyncPager` passes each
    page's opaque ``next`` token back unchanged.
    """

    # unasync: end
    """Items of a conversation (``/v1/conversations/{id}/items``). Read-only.

    The returned :class:`~introspection_sdk.pagination.Pager` passes each
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
    ) -> AsyncPager[GenAiSpan, GenAiSpanList]:
        # unasync: async-only (the sync twin's docstring follows)
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
        # unasync: end
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
    # unasync: async-only (the sync twin's docstring follows)
    """Async twin of :class:`Conversations`. Read-only
    (``/v1/conversations``).

    Both :meth:`list` and :meth:`items.list <AsyncConversationItems.list>`
    return an auto-paging :class:`~introspection_sdk.pagination.AsyncPager`
    and pass each page's opaque ``next`` token back unchanged.
    """

    # unasync: end
    """Read-only Conversations API (``/v1/conversations``).

    Both :meth:`list` and :meth:`items.list <ConversationItems.list>`
    return an auto-paging :class:`~introspection_sdk.pagination.Pager` and
    pass each page's opaque ``next`` token back unchanged.
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
        conversation_ids: builtins.list[str] | None = None,
        resolution: ConversationResolution | None = None,
        sentiment: ConversationSentiment | None = None,
        owner_key: str | None = None,
        metadata: dict[str, str] | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        format: ReadFormat = "json",
    ) -> AsyncPager[Conversation, Paginated[Conversation]]:
        # unasync: async-only (the sync twin's docstring follows)
        """List conversation summaries (cursor envelope). ``await`` the
        returned :class:`AsyncPager` for the first page, or ``async for`` it
        to stream every summary across pages. See
        :meth:`Conversations.list` for the param semantics."""
        # unasync: end
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
                conversation_ids=conversation_ids,
                resolution=resolution,
                sentiment=sentiment,
                owner_key=owner_key,
                metadata=metadata,
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
        conversation_ids: builtins.list[str] | None = None,
        resolution: ConversationResolution | None = None,
        sentiment: ConversationSentiment | None = None,
        owner_key: str | None = None,
        metadata: dict[str, str] | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
    ) -> AsyncArrowPageIterator:
        # unasync: async-only (the sync twin's docstring follows)
        """Columnar accessor: ``async for`` one ``pyarrow.Table`` per server
        page, or ``await .read_all()`` to concatenate every page into one
        Table. Same filters as :meth:`list`; requires the ``[arrow]``
        extra."""
        # unasync: end
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
                conversation_ids=conversation_ids,
                resolution=resolution,
                sentiment=sentiment,
                owner_key=owner_key,
                metadata=metadata,
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
        """Export one complete conversation as the standard GenAI-span list."""
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
        """Stream raw complete-export bytes without buffering them in the SDK."""
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
        payload = await self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(
                agent=agent,
                service_name=service_name,
                operation_name=operation_name,
                lookback_days=lookback_days,
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
        raw = await self._http.request(
            "GET",
            _export_path(conversation_id),
            params=build_export_params(
                agent=agent,
                service_name=service_name,
                operation_name=operation_name,
                lookback_days=lookback_days,
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
        # unasync: async-only (the sync twin's docstring follows)
        """Scan items in descending order for the most recent LLM turn.

        The old heuristic also matched ``node_type == "assistant"``, but
        ``node_type`` was a precomputed UI tree hint with no semantic-convention
        equivalent and is gone from the wire. ``gen_ai.operation.name`` is the
        attribute that actually carried the meaning.

        Bounded by :data:`LATEST_TURN_SCAN_LIMIT`, exactly as the sync twin.
        """
        # unasync: end
        """Scan items in descending order for the most recent LLM turn.

        The old heuristic also matched ``node_type == "assistant"``, but
        ``node_type`` was a precomputed UI tree hint with no semantic-convention
        equivalent and is gone from the wire. ``gen_ai.operation.name`` is the
        attribute that actually carried the meaning.

        Bounded by :data:`LATEST_TURN_SCAN_LIMIT`: see its note for why an
        unbounded scan was the wrong shape for this lookup.
        """
        fallback: GenAiSpan | None = None
        scanned = 0
        # The route is descending-only, so the first match is the latest.
        async for item in self.items.list(
            conversation_id, limit=LATEST_TURN_SCAN_LIMIT
        ):
            gen_ai = item.attributes.gen_ai
            operation = (
                gen_ai.operation.name if gen_ai and gen_ai.operation else None
            )
            if operation == "chat":
                return item.span_id
            if fallback is None and item.output_messages:
                fallback = item
            # Counted after the body, so the loop stops on the last item of
            # the page rather than asking the pager for the next one.
            scanned += 1
            if scanned >= LATEST_TURN_SCAN_LIMIT:
                break
        return fallback.span_id if fallback else None
