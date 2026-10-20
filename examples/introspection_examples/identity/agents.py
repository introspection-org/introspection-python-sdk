"""Run a task for an end user: name them when you open the runner, so the
task, its conversation and its memory are theirs.

Opens a runner with ``identity={"user_id": ...}``, starts a task, and prints
the ``customer`` member that owns it.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.identity.agents

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, Runner


def open_runner(
    client: IntrospectionClient, runtime: str, user_id: str
) -> Runner:
    # #region docs:identity/agents/how-agents-act
    runner = client.runtimes(runtime).run(identity={"user_id": user_id})
    # #endregion docs:identity/agents/how-agents-act
    return runner


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    # Take the user ID from your server session.
    runner = open_runner(client, runtime, "user-4821")
    try:
        handle = runner.tasks.start(prompt="Say hello in one sentence.")
        handle.text()
        task = runner.tasks.get(str(handle.run.task_id))
        print(f"task {task.id} is owned by member {task.member_id}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
