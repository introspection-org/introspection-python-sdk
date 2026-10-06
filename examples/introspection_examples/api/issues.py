"""List the project's issues, and open one when a worker task is given.

Uses ``client.issues``; the same code runs against ``runner.issues`` because
the client and the Runner share ``DataPlaneResources``.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.issues

Optional env:
    INTROSPECTION_TASK_ID       - worker task for a new issue; skips create when unset
    INTROSPECTION_BASE_API_URL  - API host (default https://api.introspection.dev)
    INTROSPECTION_DP_URL        - data-plane host, when it differs
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.protocols import DataPlaneResources


def print_open_issues(dp: DataPlaneResources) -> None:
    # A Pager: iterating follows the `next` cursor across pages.
    for issue in dp.issues.list(status=["open", "waiting"], limit=50):
        print(f"  #{issue.display_index} {issue.status:8} {issue.title}")


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient(dp_url=os.getenv("INTROSPECTION_DP_URL"))
    try:
        print_open_issues(client)

        task_id = os.getenv("INTROSPECTION_TASK_ID")
        if not task_id:
            return

        issue = client.issues.create(
            title="Example issue",
            description="Opened by the Python SDK issues example.",
            task_id=UUID(task_id),
            tags=["source:sdk-example"],
        )
        print(f"opened #{issue.display_index} at revision {issue.revision}")

        closed = client.issues.update(
            issue.id, expected_revision=issue.revision, status="cancelled"
        )
        print(f"cancelled at revision {closed.revision}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
