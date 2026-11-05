"""Open an issue, ask a member about it, and close it.

Lists the open issues the caller may read. When INTROSPECTION_TASK_ID and
INTROSPECTION_MEMBER_ID are set, it also opens an issue on that worker task,
asks that member a question on it, edits the brief at the revision it read,
and deletes the issue again.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.issues

Optional env:
    INTROSPECTION_TASK_ID       - worker task the issue lives on
    INTROSPECTION_MEMBER_ID     - member the request is assigned to
    INTROSPECTION_BASE_API_URL  - API host (default https://api.introspection.dev)
    INTROSPECTION_DP_URL        - data-plane host, when it differs
"""

from __future__ import annotations

import os
import sys
import uuid
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.schemas.issues import (
    IssueLink,
    IssueMutation,
    IssueRequestMutation,
    IssueStatus,
    IssueUpdate,
)


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient(dp_url=os.getenv("INTROSPECTION_DP_URL"))
    try:
        # A Pager: iterating follows the `next` cursor across pages.
        for issue in client.issues.list(
            status=[IssueStatus.OPEN, IssueStatus.WAITING], limit=50
        ):
            print(f"  #{issue.display_index} {issue.status:8} {issue.title}")

        task_id = os.getenv("INTROSPECTION_TASK_ID")
        member_id = os.getenv("INTROSPECTION_MEMBER_ID")
        if not (task_id and member_id):
            return

        # #region docs:issues-lifecycle
        issue = client.issues.create(
            title="Checkout times out",
            description="Stripe calls exceed 30s under load.",
            task_id=UUID(task_id),
            tags=["area:checkout"],
            # One key per deliberate write; resend it when retrying.
            idempotency_key=str(uuid.uuid4()),
        )

        # Ask a member: expected_revision=0 creates the request.
        issue = client.issues.update(
            issue.id,
            IssueMutation(
                request=IssueRequestMutation(
                    expected_revision=0,
                    question="Should we ship the retry?",
                    assignee_id=UUID(member_id),
                )
            ),
        )

        # Edit the brief at the revision just read. A list you pass replaces
        # the issue's list; `tags=[]` clears it, an omitted field is kept.
        issue = client.issues.update(
            issue.id,
            IssueUpdate(
                expected_revision=issue.revision,
                links=[IssueLink(url="https://github.com/acme/app/pull/7")],
                tags=[],
            ),
        )
        print(f"#{issue.display_index} at revision {issue.revision}")
        # #endregion docs:issues-lifecycle

        client.issues.delete(issue.id)
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
