"""Keep the user's time zone on a task, so the follow-ups the agent
schedules for itself fire in that zone.

Starts a task whose metadata carries ``timezone``; the agent reads it from
``INTROSPECTION_TASK_METADATA_JSON``. Without it, cron follow-ups run in UTC.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.agent_follow_ups

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, RunHandle, Runner


def start_in_time_zone(runner: Runner, prompt: str) -> RunHandle:
    # #region docs:patterns/agent-follow-ups/time-zone
    handle = runner.tasks.start(
        prompt=prompt, metadata={"timezone": "Europe/London"}
    )
    # #endregion docs:patterns/agent-follow-ups/time-zone
    return handle


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        handle = start_in_time_zone(
            runner, "Remind me every morning at 8 to check the refund queue."
        )
        print(f"task {handle.run.task_id}: {handle.text()}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
