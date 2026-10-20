"""Start work from your systems: one task per inbound event, and batches
sent in waves the organization's concurrency limit can take.

``handle_event`` is the body of a ``POST /webhooks/events`` route: it starts
a task and answers ``202`` at once. Run directly, the module feeds it one
sample event, then triages a small batch in waves of five.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.trigger

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from introspection_sdk import AsyncIntrospectionClient, IntrospectionClient

load_dotenv()
# The docs use triage-agent; point this at any deployed runtime.
RUNTIME = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")


# #region docs:patterns/trigger/task-per-event
def handle_event(
    client: IntrospectionClient, body: dict[str, str]
) -> tuple[int, dict[str, str]]:
    """POST /webhooks/events: start one task per event, return at once."""
    with client.runtimes(RUNTIME).run() as runner:
        handle = runner.tasks.start(
            prompt=f"New event {body['id']}:\n\n{body['text']}",
            conversation_metadata={"event_id": body["id"]},
        )
    return 202, {"task_id": str(handle.run.task_id)}


# #endregion docs:patterns/trigger/task-per-event


async def run_batch(
    client: AsyncIntrospectionClient, tickets: list[str]
) -> None:
    # #region docs:patterns/trigger/batch
    runner = await client.runtimes(RUNTIME).run()
    for i in range(0, len(tickets), 5):
        wave = await asyncio.gather(
            *(
                runner.tasks.start(
                    prompt=f"Triage ticket {t}", tags=["batch:2026-10-15"]
                )
                for t in tickets[i : i + 5]
            )
        )
        # waits for each run to settle
        await asyncio.gather(*(h.text() for h in wave))
    # #endregion docs:patterns/trigger/batch
    await runner.close()


async def batch(tickets: list[str]) -> None:
    async with AsyncIntrospectionClient() as client:
        await run_batch(client, tickets)


def main() -> None:
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient()  # reads INTROSPECTION_TOKEN
    try:
        event = {"id": "evt_1842", "text": "Customer charged twice."}
        status, body = handle_event(client, event)
        print(f"{status} {body}")
    finally:
        client.shutdown()

    tickets = ["4411", "4412", "4413"]
    asyncio.run(batch(tickets))
    print(f"triaged {len(tickets)} tickets tagged batch:2026-10-15")


if __name__ == "__main__":
    main()
