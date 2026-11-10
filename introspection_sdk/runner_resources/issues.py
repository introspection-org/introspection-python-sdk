"""``client.issues`` / ``runner.issues``: DP namespace for ``/v1/issues``.

An issue is a brief (title, description, priority, status) on a fixed
worker Task, which carries its chat and Slack replies, with the people on
it, the evidence it cites and its comments. ``update`` takes an
:class:`~introspection_sdk.schemas.issues.IssueUpdate`; ``comments.create``
posts a comment. An update and a delete take an optional ``if_match`` (an
issue's ``etag``), refused with 412 if the issue changed since that read.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.issues import (
    AsyncIssueComments,
    AsyncIssues,
)
from introspection_sdk._sync.runner_resources.issues import (
    IssueComments,
    Issues,
)

__all__ = [
    "AsyncIssueComments",
    "AsyncIssues",
    "IssueComments",
    "Issues",
]
