"""DP-bound namespaces hung off a :class:`Runner` instance."""

from introspection_sdk.runner_resources.files import Files, FileVersions
from introspection_sdk.runner_resources.tasks import (
    RunHandle,
    TaskRuns,
    Tasks,
)

__all__ = [
    "Files",
    "FileVersions",
    "RunHandle",
    "TaskRuns",
    "Tasks",
]
