"""Python SDK reference: reattach, interrupts, cancel, files, reads and
feedback against one task.

Backs the docs' Python SDK page past "Run a task" (regions
``reference/python/{reattach,answer-interrupt,cancel,files,``
``conversations-events-metrics,feedback}``). Each region is the body of
one function below; ``main`` supplies the ``runner``, ``task_id``, ``run``
and ``interrupt`` the snippets take as given.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.reference.python_sdk

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from ag_ui.core import RunFinishedInterruptOutcome
from dotenv import load_dotenv
from introspection_sdk import (
    AsyncIntrospectionClient,
    AsyncRunHandle,
    AsyncRunner,
    ConflictError,
    Interrupt,
)
from introspection_sdk.schemas.agui import AGUIEvent, RunFinishedEvent


# The regions keep the docs' line lengths, not the formatter's.
# fmt: off
async def reattach(runner: AsyncRunner, task_id: str) -> None:
# #region docs:reference/python/reattach
    # Your app's code: show the event in your UI.
    def render(event: AGUIEvent) -> None:
        print(event.model_dump_json(by_alias=True, exclude_none=True))

    task = await runner.tasks.get(task_id)
    metadata = task.metadata or {}
    run_id = metadata.get("active_run_id") or metadata["latest_run_id"]
    async for event in runner.tasks.runs.stream(task_id, run_id):
        render(event)
# #endregion docs:reference/python/reattach


async def answer_interrupt(
    runner: AsyncRunner, task_id: str, interrupt: Interrupt
) -> AsyncRunHandle:
# #region docs:reference/python/answer-interrupt
    from introspection_sdk import ResumeEntry

    resumed = await runner.tasks.runs.resume(
        task_id,
        resume=[ResumeEntry(interrupt_id=interrupt.id, status="resolved", payload={"approved": True})],
    )
# #endregion docs:reference/python/answer-interrupt
    return resumed


async def cancel(run: AsyncRunHandle) -> None:
# #region docs:reference/python/cancel
    await run.cancel()  # abort the turn, keep the sandbox warm
    await run.cancel({"mode": "drain", "drain_within_seconds": 60})
# #endregion docs:reference/python/cancel


async def files(runner: AsyncRunner) -> AsyncRunHandle:
# #region docs:reference/python/files
    from pathlib import Path

    uploaded = await runner.files.upload(file=Path("spec.md"), file_type="upload")
    run = await runner.tasks.start(prompt="Summarize spec.md.", files=[{"id": str(uploaded.id)}])
# #endregion docs:reference/python/files
    return run


async def conversations_events_metrics(runner: AsyncRunner, task_id: str) -> None:
# #region docs:reference/python/conversations-events-metrics
    from introspection_sdk.schemas import FeedbackEvent

    async for c in runner.conversations.list(limit=20, order="desc"):
        print(c.id, c.cost.usd)

    # Tool calls only, e.g. a submit_result tool's arguments (a JSON string)
    async for item in runner.conversations.items.list(task_id, operation_name="execute_tool"):
        tool = item.attributes.gen_ai.tool if item.attributes.gen_ai else None
        if tool and tool.call:
            print(tool.name, tool.call.arguments)

    async for event in runner.events.list("introspection.feedback", conversation_id=task_id):
        if isinstance(event, FeedbackEvent):
            print(event.payload.name)

    result = await runner.metrics.query({
        "view": "conversations",
        "metrics": [{"measure": "total_cost_usd", "aggregation": "sum"}],
        "from_timestamp": "2026-07-01T00:00:00Z",
        "to_timestamp": "2026-07-08T00:00:00Z",
    })
# #endregion docs:reference/python/conversations-events-metrics
    print(result.model_dump_json(exclude_none=True))


def feedback(task_id: str) -> None:
# #region docs:reference/python/feedback
    from introspection_sdk import IntrospectionLogs

    logs = IntrospectionLogs(service_name="support-api")
    logs.feedback("thumbs_down", conversation_id=task_id, comments="Missed the refund policy", value=0)
    logs.track("case_closed", {"source": "web"})
    logs.shutdown()
# #endregion docs:reference/python/feedback
# fmt: on


async def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        raise SystemExit(
            "INTROSPECTION_TOKEN is not set: export a project API key "
            "(intro_...) or add it to .env"
        )
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    # The files snippet uploads ./spec.md; give it one in a scratch dir.
    os.chdir(tempfile.mkdtemp())
    with open("spec.md", "w") as fh:
        fh.write("# Spec\n\nReply to every ticket within one business day.\n")

    async with AsyncIntrospectionClient() as client:
        runner = await client.runtimes(runtime).run(
            identity={"user_id": "user_123"}
        )
        async with runner:
            run = await files(runner)
            task_id = str(run.run.task_id)

            interrupts: list[Interrupt] = []
            async for event in run.stream():
                if isinstance(event, RunFinishedEvent) and isinstance(
                    event.outcome, RunFinishedInterruptOutcome
                ):
                    interrupts = event.outcome.interrupts
            print(f"task={task_id} finished, {len(interrupts)} interrupt(s)")

            await reattach(runner, task_id)
            for interrupt in interrupts:
                resumed = await answer_interrupt(runner, task_id, interrupt)
                print(await resumed.text())

            await conversations_events_metrics(runner, task_id)

            # A run to cancel: the first call aborts the turn; the run may
            # already have settled before the drain request lands.
            long_run = await runner.tasks.runs.create(
                task_id,
                kind="prompt",
                prompt={"text": "Count slowly from one to one hundred."},
            )
            try:
                await cancel(long_run)
            except ConflictError as exc:
                print(f"run already settled: {exc}")

    feedback(task_id)


if __name__ == "__main__":
    asyncio.run(main())
