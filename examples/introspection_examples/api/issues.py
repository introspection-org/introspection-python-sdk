"""Open an issue, ask a member about it, and close it.

Lists the open issues the caller may read. When INTROSPECTION_TASK_ID and
INTROSPECTION_MEMBER_ID are set, it also opens an issue on that worker task,
asks that member a question (assign, move to waiting, comment), reads the
comments back, edits the brief against the version it read, and deletes the
issue again.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.issues

Optional env:
    INTROSPECTION_TASK_ID       - worker task the issue lives on
    INTROSPECTION_MEMBER_ID     - member the issue is assigned to
    INTROSPECTION_BASE_API_URL  - API host (default https://api.introspection.dev)
    INTROSPECTION_DP_URL        - data-plane host, when it differs
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.schemas.issues import (
    IssueLink,
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
        )

        # Ask a member: assign the issue, move it to waiting, and post the
        # question as a comment.
        issue = client.issues.update(
            issue.id,
            IssueUpdate(
                assignee_member_id=UUID(member_id),
                status=IssueStatus.WAITING,
            ),
        )
        client.issues.comments.create(
            issue.id, comment="Should we ship the retry?"
        )

        # Comments are read with the issue. One just posted is an event
        # still being ingested, so it may not be here yet.
        issue = client.issues.get(issue.id, include=["members", "comments"])
        for comment in issue.comments or []:
            print(
                f"  {comment.created_at} {comment.member_id}: {comment.comment}"
            )

        # Edit the brief; `if_match` refuses it (412) if the issue changed
        # since the read. A list you pass replaces the issue's list;
        # `tags=[]` clears it, an omitted field is kept.
        issue = client.issues.update(
            issue.id,
            IssueUpdate(
                links=[IssueLink(url="https://github.com/acme/app/pull/7")],
                tags=[],
            ),
            if_match=issue.etag,
        )
        print(f"#{issue.display_index} at version {issue.etag}")
        # #endregion docs:issues-lifecycle

        client.issues.delete(issue.id)
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
