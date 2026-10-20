"""Send feedback and a business event for a conversation from your backend.

Starts a task so there is an answer to rate, then rates that answer with
``IntrospectionLogs.feedback`` and records a ``case_closed`` business event
with ``track``, both scoped to the end user. Feedback reads back as
``introspection.feedback`` events once the platform has indexed it.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.observe.feedback_events

Optional env:
    INTROSPECTION_RUNTIME        - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL   - CP REST API host
    INTROSPECTION_BASE_OTEL_URL  - OTLP collector
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.otel import IntrospectionLogs
from introspection_sdk.schemas.tasks import Task


def send_feedback(user_id: str, task: Task) -> IntrospectionLogs:
    # #region docs:observe/patterns/feedback-events
    logs = IntrospectionLogs(service_name="support-api")

    with logs.set_user_id(user_id):
        last_response = (task.metadata or {}).get("last_response") or {}
        logs.feedback(
            "thumbs_down",
            conversation_id=str(task.id),
            # the answer being rated
            previous_response_id=last_response.get("response_id"),
            comments="Applied the wrong refund rule",
        )
        logs.track("case_closed", {"value": 1, "plan": "pro"})
    # #endregion docs:observe/patterns/feedback-events
    return logs


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")
    user_id = "user-4821"

    client = IntrospectionClient()
    runner = client.runtimes(runtime).run(identity={"user_id": user_id})
    try:
        handle = runner.tasks.start(prompt="Say hello in one sentence.")
        print(f"answer: {handle.text()}")
        task = runner.tasks.get(str(handle.run.task_id))
    finally:
        runner.close()
        client.shutdown()

    logs = send_feedback(user_id, task)
    try:
        logs.flush()
    finally:
        logs.shutdown()
    print(f"sent thumbs_down and case_closed for conversation {task.id}")


if __name__ == "__main__":
    main()
