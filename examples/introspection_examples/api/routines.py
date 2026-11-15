"""Schedule a one-off reminder into a task and read its trigger events.

Lists the project's routines, then (when INTROSPECTION_TASK_ID and
INTROSPECTION_RUNTIME_GROUP_ID are set) creates a ``manual`` routine that
posts a prompt into that task an hour from now, and reads back the
``introspection.routines.triggered`` events for it.

The server serves ``/v1/routines`` to project administrators only today;
introspection-cloud#3137 opens it to members for their own task-targeted
routines.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.routines

Optional env:
    INTROSPECTION_TASK_ID           - task the reminder posts into
    INTROSPECTION_RUNTIME_GROUP_ID  - runtime group the task runs on
    INTROSPECTION_BASE_API_URL      - API host (default https://api.introspection.dev)
    INTROSPECTION_DP_URL            - data-plane host, when it differs
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient(dp_url=os.getenv("INTROSPECTION_DP_URL"))
    try:
        # A Pager: iterating follows the `next` cursor across pages.
        for routine in client.routines.list(limit=50):
            print(
                f"  {routine.kind or 'prompt':22} {routine.name}"
                f" next={routine.next_trigger_at}"
            )

        task_id = os.getenv("INTROSPECTION_TASK_ID")
        runtime_group_id = os.getenv("INTROSPECTION_RUNTIME_GROUP_ID")
        if not (task_id and runtime_group_id):
            return

        reminder = client.routines.create(
            name="Check in",
            trigger_type="manual",
            prompt="Any progress since we last spoke?",
            runtime_group_id=UUID(runtime_group_id),
            task_id=UUID(task_id),
            next_trigger_at=datetime.now(UTC) + timedelta(hours=1),
        )
        print(f"scheduled {reminder.id} for {reminder.next_trigger_at}")

        for event in client.events.list(
            "introspection.routines.triggered",
            routine_id=reminder.id,
            lookback="7d",
        ):
            print(f"  triggered at {event.timestamp}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
