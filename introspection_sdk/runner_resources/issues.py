"""``client.issues`` / ``runner.issues``: DP namespace for ``/v1/issues``.

An issue is a brief (title, description, priority, status) with the
evidence it cites (files, links, events, spans) and the human requests
open on it. It lives on a fixed worker Task, which carries its chat and
Slack replies. ``update`` takes either an
:class:`~introspection_sdk.schemas.issues.IssueUpdate`, which edits the
brief at an ``expected_revision``, or an
:class:`~introspection_sdk.schemas.issues.IssueMutation`, which creates or
changes one human request. Every write takes an optional
``idempotency_key``; resend it unchanged when retrying that write.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.issues import AsyncIssues
from introspection_sdk._sync.runner_resources.issues import Issues

__all__ = [
    "AsyncIssues",
    "Issues",
]
