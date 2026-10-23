"""`runner.tasks.*` namespace: tasks + runs + commands + cursor-style sugar.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.tasks import (
    MAX_COMMAND_WAIT_SECONDS,
    AsyncRunHandle,
    AsyncTaskCommands,
    AsyncTaskRuns,
    AsyncTasks,
)
from introspection_sdk._sync.runner_resources.tasks import (
    RunHandle,
    TaskCommands,
    TaskRuns,
    Tasks,
)

__all__ = [
    "MAX_COMMAND_WAIT_SECONDS",
    "AsyncRunHandle",
    "AsyncTaskCommands",
    "AsyncTaskRuns",
    "AsyncTasks",
    "RunHandle",
    "TaskCommands",
    "TaskRuns",
    "Tasks",
]
