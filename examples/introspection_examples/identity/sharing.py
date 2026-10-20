"""Share an end user's own conversation from their runner.

Opens a runner for an end user, runs one turn, and shares the resulting
conversation (the task ID) with one member, or with the whole project when
no member is named. The share is deleted again at the end.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.identity.sharing

Optional env:
    INTROSPECTION_GRANTEE_MEMBER_ID  - member to share with (default: project)
    INTROSPECTION_RUNTIME            - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL       - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, Runner
from introspection_sdk.schemas.shares import ResourceShare


def share_conversation(
    runner: Runner, task_id: str, granted_member_id: str | None
) -> ResourceShare:
    # #region docs:identity/sharing/share
    share = runner.shares.create(
        resource_type="conversation",
        resource_id=task_id,
        granted_member_id=granted_member_id,
    )
    # #endregion docs:identity/sharing/share
    return share


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")
    granted_member_id = os.getenv("INTROSPECTION_GRANTEE_MEMBER_ID")

    client = IntrospectionClient()
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        handle = runner.tasks.start(prompt="Say hello in one sentence.")
        handle.text()
        task_id = str(handle.run.task_id)
        share = share_conversation(runner, task_id, granted_member_id)
        audience = granted_member_id or "the project"
        print(f"shared conversation {task_id} with {audience}: {share.url}")
        runner.shares.delete(str(share.id))
        print(f"deleted share {share.id}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
