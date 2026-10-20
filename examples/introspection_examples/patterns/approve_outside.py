"""Tell the agent what a person did with its draft.

Runs one turn, then posts the outcome into the task as a steer: a
``<user_action>`` tag that the recipe's ``SYSTEM.md`` describes as a record
of what a person did, never a request.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.approve_outside

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, RunHandle, Runner


def report_outcome(runner: Runner, task_id: str) -> RunHandle:
    # #region docs:patterns/approve-outside/report-outcome
    handle = runner.tasks.runs.create(
        task_id,
        kind="steer",
        prompt={
            "text": '<user_action kind="draft" action="sent" id="d-17" by="maria">Sent text</user_action>'
        },
    )
    # #endregion docs:patterns/approve-outside/report-outcome
    return handle


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    # Steer with a runner opened for the identity that started the task.
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        handle = runner.tasks.start(
            prompt="Draft a short reply to a customer asking for a refund."
        )
        print(f"draft: {handle.text()}")
        task_id = str(handle.run.task_id)
        print(f"agent: {report_outcome(runner, task_id).text()}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
