"""Run a task for a signed-in user from your backend, reconnect to it, and
record the user's feedback on the answer.

Mints a service-account token, opens a runner for the end user, starts a
task and saves its ID before streaming, replays the run as a reload would,
then sends thumbs-down feedback tied to the answer it rates.

Run with:
    INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID=intro_app_xxx
    INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET=intro_sk_xxx
    INTROSPECTION_PROJECT=<project-slug>
    INTROSPECTION_API_KEY=intro_xxx

        uv run -m introspection_examples.patterns.add_to_your_app

Optional env:
    INTROSPECTION_RUNTIME        - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL   - CP REST API host
    INTROSPECTION_BASE_OTEL_URL  - OTLP collector
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, Runner
from introspection_sdk.otel import IntrospectionLogs
from introspection_sdk.schemas import AGUIEvent

REQUIRED_ENV = (
    "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID",
    "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET",
    "INTROSPECTION_PROJECT",
    "INTROSPECTION_API_KEY",
)


@dataclass
class AgentBinding:
    task_id: str
    user_id: str


class Orders:
    """Stands in for your database: which task works on which order."""

    def __init__(self) -> None:
        self.bindings: dict[str, AgentBinding] = {}

    def save_agent_binding(
        self, order_id: str, *, task_id: str, user_id: str
    ) -> None:
        self.bindings[order_id] = AgentBinding(task_id, user_id)


orders = Orders()


def send_event_to_browser(event: AGUIEvent) -> None:
    """Stands in for your server-sent events or WebSocket push."""
    print(f"  -> browser: {event.type}")


def open_runner(
    runtime: str, user_id: str
) -> tuple[IntrospectionClient, IntrospectionLogs, Runner]:
    # #region docs:patterns/add-to-your-app/open-runner
    client = IntrospectionClient.from_service_account(
        client_id=os.environ["INTROSPECTION_SERVICE_ACCOUNT_CLIENT_ID"],
        client_secret=os.environ[
            "INTROSPECTION_SERVICE_ACCOUNT_CLIENT_SECRET"
        ],
        project=os.environ["INTROSPECTION_PROJECT"],
    )
    # An API key: this logger keeps one token for life.
    outcomes = IntrospectionLogs(
        token=os.environ["INTROSPECTION_API_KEY"], service_name="refund-app"
    )

    runner = client.runtimes(runtime).run(identity={"user_id": user_id})
    # #endregion docs:patterns/add-to-your-app/open-runner
    return client, outcomes, runner


def start_task(runner: Runner, order_id: str, user_id: str) -> None:
    # #region docs:patterns/add-to-your-app/start-task
    handle = runner.tasks.start(
        prompt="Review order 1842 against the refund policy and draft the next response.",
        metadata={"order_id": "1842"},
    )
    orders.save_agent_binding(
        order_id, task_id=str(handle.run.task_id), user_id=user_id
    )

    for event in handle.stream():
        send_event_to_browser(event)
    # #endregion docs:patterns/add-to-your-app/start-task


def reconnect(runner: Runner, binding: AgentBinding) -> None:
    # #region docs:patterns/add-to-your-app/reconnect
    task = runner.tasks.get(binding.task_id)
    metadata = task.metadata or {}
    run_id = metadata.get("active_run_id") or metadata["latest_run_id"]
    for event in runner.tasks.runs.stream(binding.task_id, run_id):
        send_event_to_browser(event)
    # #endregion docs:patterns/add-to-your-app/reconnect


def record_feedback(
    runner: Runner, outcomes: IntrospectionLogs, binding: AgentBinding
) -> None:
    # #region docs:patterns/add-to-your-app/feedback
    task = runner.tasks.get(binding.task_id)
    last_response = (task.metadata or {}).get("last_response") or {}
    outcomes.feedback(
        "thumbs_down",
        conversation_id=binding.task_id,
        previous_response_id=last_response.get("response_id"),
        comments="Missed the final-sale rule",
    )
    outcomes.flush()
    # #endregion docs:patterns/add-to-your-app/feedback


def main() -> None:
    load_dotenv()
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        # Not an error: the examples workflow runs this module whether or
        # not the repository has service-account secrets configured.
        print(
            f"skipping: set {', '.join(missing)} (a service account's client "
            "ID and secret, its project slug, and a project API key) to run "
            "this example",
            file=sys.stderr,
        )
        return
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")
    user_id = "user-4821"  # take it from your server session

    client, outcomes, runner = open_runner(runtime, user_id)
    try:
        start_task(runner, "1842", user_id)
        binding = orders.bindings["1842"]
        print(f"task {binding.task_id} saved for order 1842")

        # After a reload: check the record belongs to the signed-in user.
        if binding.user_id != user_id:
            sys.exit("that task belongs to another user")
        reconnect(runner, binding)

        record_feedback(runner, outcomes, binding)
        print(f"sent thumbs_down for conversation {binding.task_id}")
    finally:
        outcomes.shutdown()
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
