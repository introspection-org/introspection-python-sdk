"""`runner.tasks.*` namespace: tasks + runs + cursor-style sugar.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call
targets the runner's DP endpoint with its short-lived JWT.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.tasks import (
    AsyncRunHandle,
    AsyncTaskRuns,
    AsyncTasks,
)
from introspection_sdk._sync.runner_resources.tasks import (
    RunHandle,
    TaskRuns,
    Tasks,
)

__all__ = [
    "AsyncRunHandle",
    "AsyncTaskRuns",
    "AsyncTasks",
    "RunHandle",
    "TaskRuns",
    "Tasks",
]
