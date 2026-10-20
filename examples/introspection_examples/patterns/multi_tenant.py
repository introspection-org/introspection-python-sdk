"""Serve many customers from one runtime: name the end user on every task
and pass each customer's configuration as task metadata.

Opens a runner for an end user tagged with their customer, starts a task
with the customer's playbook in ``metadata`` and the customer tag on the
task, then lists that customer's tasks by tag.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.multi_tenant

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import (
    IntrospectionClient,
    RunHandle,
    Runner,
)


def open_runner(
    client: IntrospectionClient, runtime: str, user_id: str
) -> Runner:
    # #region docs:patterns/multi-tenant/end-user
    runner = client.runtimes(runtime).run(
        identity={"user_id": user_id, "tags": ["customer:acme"]},
    )
    # #endregion docs:patterns/multi-tenant/end-user
    return runner


def start_for_customer(runner: Runner, prompt: str) -> RunHandle:
    # #region docs:patterns/multi-tenant/per-task-config
    handle = runner.tasks.start(
        prompt=prompt,
        metadata={"customer": "acme", "playbook": "acme-v3", "region": "eu"},
        tags=["customer:acme"],
    )
    # #endregion docs:patterns/multi-tenant/per-task-config
    return handle


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    # Take the user ID from your server session.
    runner = open_runner(client, runtime, "user-4821")
    try:
        handle = start_for_customer(
            runner, "Which playbook are you following for this customer?"
        )
        print(f"task {handle.run.task_id}: {handle.text()}")
        page = runner.tasks.list(tag="customer:acme", limit=10).page()
        for task in page.records:
            print(f"  acme task {task.id} ({task.status})")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
