"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.conversations`."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any, Literal, TypedDict
from urllib.parse import quote
from uuid import UUID

from pydantic import TypeAdapter

from introspection_sdk.runner_resources._reads import (
    ARROW_ACCEPT_HEADERS,
    TRAJECTORY_ACCEPT_HEADERS,
)
from introspection_sdk.schemas.conversations import (
    ConversationSortField,
    SpanStatus,
)
from introspection_sdk.schemas.genai_span import GenAiSpanList
from introspection_sdk.schemas.trajectory import TrajectoryRecord

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
    start_date: str | datetime
    end_date: str | datetime


JSON_EXPORT_HEADERS = {"Accept": "application/json"}


#: How many items ``retrieve()`` scans, newest-first, looking for the latest
#: LLM turn. The scan used to be unbounded: it drove the auto-paging
#: ``Pager`` and, on a conversation whose recent items are all tool or
#: retrieval spans, walked every turn ever recorded -- one request per page,
#: for a lookup the caller expects to cost one or two. The turn it wants is
#: at the head of a descending list; if it is not in the first page, the
#: caller wants ``items.list()`` and their own predicate, not this heuristic.
#: Deliberately below the list route's default page size, so the bound is the
#: request the SDK asks for and not just a local slice of a larger page.
LATEST_TURN_SCAN_LIMIT = 50


def build_export_params(
    *,
    agent: str | None = None,
    service_name: str | None = None,
    operation_name: str | None = None,
    lookback_days: int | None = None,
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


ConversationResolution = Literal[
    "resolved", "blocked", "unresolved", "pending"
]


"""``resolution`` filter on the conversations list."""


ConversationSentiment = Literal["positive", "negative", "mixed", "neutral"]


"""``sentiment`` filter on the conversations list."""


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
    conversation_ids: builtins.list[str] | None = None,
    resolution: ConversationResolution | None = None,
    sentiment: ConversationSentiment | None = None,
    owner_key: str | None = None,
    metadata: dict[str, str] | None = None,
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
        "conversation_ids": conversation_ids,
        "resolution": resolution,
        "sentiment": sentiment,
        "owner_key": owner_key,
        "metadata": (
            [f"{key}:{value}" for key, value in metadata.items()]
            if metadata
            else None
        ),
        "start_date": start_date,
        "end_date": end_date,
    }


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
