"""Typing Protocols for the data-plane namespaces.

:class:`DataPlaneResources` is the interface the client and the
:class:`~introspection_sdk.runner.Runner` share on the data plane, and
:class:`AsyncDataPlaneResources` its async twin. Each namespace is a
Protocol of its methods too, so code written against these runs with
either handle, and the type checker fails when the two drift apart.

The two differ in credential, not in shape: the client sends its own token
(an API key, a service account or a member's token) and the Runner sends
the session token minted for it. ``runner.connections.create`` takes
``runtime`` as optional, defaulting to the runner's runtime group, which
still satisfies the Protocol, where ``runtime`` is required.
"""

from __future__ import annotations

from introspection_sdk._async.protocols import (
    AsyncAutomationsResource,
    AsyncConnectionsResource,
    AsyncConversationItemsResource,
    AsyncConversationsResource,
    AsyncDataPlaneResources,
    AsyncEventsResource,
    AsyncFilesResource,
    AsyncFileVersionsResource,
    AsyncMetricsResource,
    AsyncSharesResource,
    AsyncTaskRunsResource,
    AsyncTasksResource,
)
from introspection_sdk._sync.protocols import (
    AutomationsResource,
    ConnectionsResource,
    ConversationItemsResource,
    ConversationsResource,
    DataPlaneResources,
    EventsResource,
    FilesResource,
    FileVersionsResource,
    MetricsResource,
    SharesResource,
    TaskRunsResource,
    TasksResource,
)

__all__ = [
    "AsyncAutomationsResource",
    "AsyncConnectionsResource",
    "AsyncConversationItemsResource",
    "AsyncConversationsResource",
    "AsyncDataPlaneResources",
    "AsyncEventsResource",
    "AsyncFileVersionsResource",
    "AsyncFilesResource",
    "AsyncMetricsResource",
    "AsyncSharesResource",
    "AsyncTaskRunsResource",
    "AsyncTasksResource",
    "AutomationsResource",
    "ConnectionsResource",
    "ConversationItemsResource",
    "ConversationsResource",
    "DataPlaneResources",
    "EventsResource",
    "FileVersionsResource",
    "FilesResource",
    "MetricsResource",
    "SharesResource",
    "TaskRunsResource",
    "TasksResource",
]
