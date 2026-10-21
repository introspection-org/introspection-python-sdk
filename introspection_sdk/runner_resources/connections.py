"""``client.connections`` / ``runner.connections`` — DP namespace for
``/v1/connections``: the apps (Gmail, Slack, ...) members connected for
themselves, which the agent then acts with in that member's sessions.

These are distinct from a connector's connections
(``client.connectors.connections``, CP ``/v1/connectors/{id}/connections``),
which an integrator administers for the project.

The routes take the ``connections:read``, ``connections:write`` and
``connections:delete`` scopes. A caller who is not a project administrator
only ever sees and manages their own connections, whatever ``member_id``
it asks for.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.connections import (
    AsyncAppConnections,
    AsyncRunnerAppConnections,
)
from introspection_sdk._sync.runner_resources.connections import (
    AppConnections,
    RunnerAppConnections,
)
from introspection_sdk.runner_resources._connections_common import (
    CONNECTIONS_PATH,
)

__all__ = [
    "AppConnections",
    "AsyncAppConnections",
    "AsyncRunnerAppConnections",
    "CONNECTIONS_PATH",
    "RunnerAppConnections",
]
