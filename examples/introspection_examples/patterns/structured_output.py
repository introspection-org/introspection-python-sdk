"""Get structured output back through a typed submit tool.

Starts a task, collects the arguments of the agent's ``submit_result`` call
from the stream, and validates them against the ``Triage`` schema. When the
call is missing or invalid, it asks the agent once more. The recipe needs
the ``submit_result`` tool from the docs page.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.patterns.structured_output

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id (default customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host
"""

from __future__ import annotations

import os
import sys
from typing import Literal

from ag_ui.core import ToolCallArgsEvent, ToolCallStartEvent
from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, Runner
from pydantic import BaseModel, Field, ValidationError


class Triage(BaseModel):
    """The submit tool's schema, mirrored for validation."""

    category: Literal["billing", "bug", "other"]
    priority: int = Field(ge=1, le=4)
    summary: str = Field(max_length=280)


def read_stream(runner: Runner) -> tuple[str, str | None]:
    # #region docs:patterns/structured-output/read-stream
    handle = runner.tasks.start(prompt="Triage ticket 4411: ...")
    args: dict[str, str] = {}
    submit_id: str | None = None

    for event in handle.stream():
        if (
            isinstance(event, ToolCallStartEvent)
            and event.tool_call_name == "submit_result"
        ):
            submit_id = event.tool_call_id
        if isinstance(event, ToolCallArgsEvent):
            args[event.tool_call_id] = (
                args.get(event.tool_call_id, "") + event.delta
            )
    raw = args.get(submit_id) if submit_id else None
    # #endregion docs:patterns/structured-output/read-stream
    return str(handle.run.task_id), raw


def validate(runner: Runner, task_id: str, raw: str | None) -> Triage | None:
    # #region docs:patterns/structured-output/validate
    try:
        result = Triage.model_validate_json(raw or "")
    except ValidationError:
        result = None
        runner.tasks.runs.create(
            task_id,
            kind="prompt",
            prompt={
                "text": "You did not call submit_result with a valid triage. Call it now."
            },
        )
    # #endregion docs:patterns/structured-output/validate
    return result


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    runtime = os.getenv("INTROSPECTION_RUNTIME", "customer-agent")

    client = IntrospectionClient()
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        task_id, raw = read_stream(runner)
        result = validate(runner, task_id, raw)
        if result is None:
            print(f"no valid triage on task {task_id}: asked the agent again")
        else:
            print(f"triage: {result.model_dump_json()}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
