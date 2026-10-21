"""`runner.conversations.*` namespace: read-only conversation reads.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. The surface is
read-only.

Both conversation summaries and conversation items walk opaque ``next``
cursors. The item envelope retains OpenAI-style ``first_id`` / ``last_id``
metadata, but those identifiers do not drive pagination.

Shares are ambient: a conversation shared with the caller appears in these
reads without naming the share.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.conversations import (
    AsyncConversationItems,
    AsyncConversations,
)
from introspection_sdk._sync.runner_resources.conversations import (
    ConversationItems,
    Conversations,
)
from introspection_sdk.runner_resources._conversations_common import (
    JSON_EXPORT_HEADERS,
    LATEST_TURN_SCAN_LIMIT,
    TRAJECTORY_ADAPTER,
    ConversationExportFormat,
    ConversationExportParams,
    ConversationResolution,
    ConversationSentiment,
    build_conversation_params,
    build_export_params,
)

__all__ = [
    "AsyncConversationItems",
    "AsyncConversations",
    "ConversationExportFormat",
    "ConversationExportParams",
    "ConversationItems",
    "ConversationResolution",
    "ConversationSentiment",
    "Conversations",
    "JSON_EXPORT_HEADERS",
    "LATEST_TURN_SCAN_LIMIT",
    "TRAJECTORY_ADAPTER",
    "build_conversation_params",
    "build_export_params",
]
