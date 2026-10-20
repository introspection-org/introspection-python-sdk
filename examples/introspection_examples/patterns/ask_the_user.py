"""Detect that a task paused for the user, then resume it with the answer.

Starts a task, watches its stream for a run that finishes with an interrupt
outcome, and resumes it with an answer to the first pending interrupt. The
recipe needs the ``ask_user_question`` tool from the docs page; without it
the agent never pauses and the example says so.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.ask_the_user

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys

from ag_ui.core import RunFinishedEvent, RunFinishedInterruptOutcome
from dotenv import load_dotenv
from introspection_sdk import (
    Interrupt,
    IntrospectionClient,
    ResumeEntry,
    RunHandle,
    Runner,
)


def detect_pause(handle: RunHandle) -> list[Interrupt]:
    # #region docs:patterns/ask-the-user/detect-pause
    interrupts: list[Interrupt] = []
    for event in handle.stream():
        if isinstance(event, RunFinishedEvent) and isinstance(
            event.outcome, RunFinishedInterruptOutcome
        ):
            interrupts = event.outcome.interrupts
    # #endregion docs:patterns/ask-the-user/detect-pause
    return interrupts


def resume(
    runner: Runner, task_id: str, interrupts: list[Interrupt]
) -> RunHandle:
    # #region docs:patterns/ask-the-user/resume
    handle = runner.tasks.runs.resume(
        task_id,
        resume=[
            ResumeEntry(
                interrupt_id=interrupts[0].id,
                status="resolved",
                payload={"answer": "EU"},
            )
        ],
    )
    # #endregion docs:patterns/ask-the-user/resume
    return handle


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    # Resume with the same credential that owns the task.
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        handle = runner.tasks.start(
            prompt=(
                "Before you answer, ask me which region my account is in "
                "with ask_user_question. Then name that region's VAT rate."
            )
        )
        interrupts = detect_pause(handle)
        if not interrupts:
            print("the run finished without pausing: add the ask tools")
            return
        print(f"paused: {interrupts[0].message}")
        task_id = str(handle.run.task_id)
        print(f"agent: {resume(runner, task_id, interrupts).text()}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
