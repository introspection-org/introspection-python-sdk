"""Open a conversation from a Harbor ATIF trajectory, then run an instruction.

Converts an ATIF trajectory (Harbor's ``trajectory.json``) into
``ag_ui.core`` messages with ``atif_to_messages`` and prints them. With
``INTROSPECTION_RUNTIME`` set, it also creates a task on that runtime and
opens its empty conversation with those messages: the trajectory is loaded
without a model call and the instruction runs as the turn's prompt, the way a
Harbor adapter's ``load()`` seeds a session.

Run with:
    uv run -m introspection_examples.api.load_trajectory [trajectory.json]

Without a file it converts a small built-in trajectory, the shape of
Harbor's ``hello-load-atif-trajectory`` example. Converting needs no token;
running does:

    INTROSPECTION_TOKEN=intro_xxx INTROSPECTION_RUNTIME=customer-agent \\
        uv run -m introspection_examples.api.load_trajectory trajectory.json

Optional env:
    INTROSPECTION_RUNTIME       - runtime slug or id to run on (default: convert only)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, RunHandle, Runner
from introspection_sdk.atif_messages import (
    AtifConversionError,
    atif_to_messages,
)

INSTRUCTION = (
    "Earlier in this conversation you created a file. Write its name and "
    "its content to /app/recall.txt."
)

SAMPLE: dict[str, Any] = {
    "schema_version": "ATIF-v1.7",
    "agent": {"name": "claude-code", "version": "2.1.222"},
    "steps": [
        {
            "step_id": 1,
            "source": "user",
            "message": 'Create hello.txt with "Hello, world!" as the content.',
        },
        {
            "step_id": 2,
            "source": "agent",
            "message": "",
            "tool_calls": [
                {
                    "tool_call_id": "toolu_1",
                    "function_name": "Write",
                    "arguments": {
                        "file_path": "/app/hello.txt",
                        "content": "Hello, world!\n",
                    },
                }
            ],
            "observation": {
                "results": [
                    {
                        "source_call_id": "toolu_1",
                        "content": "File created at /app/hello.txt",
                    }
                ]
            },
        },
        {"step_id": 3, "source": "agent", "message": "Created hello.txt."},
    ],
}


def load_and_run(
    runner: Runner, trajectory: dict[str, Any], instruction: str
) -> RunHandle:
    """Open a new task's conversation from ``trajectory``, then run ``instruction``."""
    messages = atif_to_messages(trajectory, prompt=instruction)
    # A task created without a prompt has an empty conversation, the only
    # one a run with messages may open.
    task = runner.tasks.create(title="Loaded from a Harbor trajectory").task
    return runner.tasks.runs.create(str(task.id), messages=messages)


def main() -> None:
    load_dotenv()
    trajectory = (
        json.loads(Path(sys.argv[1]).read_text())
        if len(sys.argv) > 1
        else SAMPLE
    )
    try:
        messages = atif_to_messages(trajectory, prompt=INSTRUCTION)
    except AtifConversionError as error:
        sys.exit(f"cannot load this trajectory: {error}")
    for message in messages:
        print(message.model_dump_json(by_alias=True, exclude_none=True)[:120])

    runtime = os.getenv("INTROSPECTION_RUNTIME")
    if not runtime:
        print("set INTROSPECTION_RUNTIME to run it on a runtime")
        return
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
    client = IntrospectionClient()
    runner = client.runtimes(runtime).run(identity={"user_id": "user-4821"})
    try:
        handle = load_and_run(runner, trajectory, INSTRUCTION)
        print(f"task {handle.run.task_id}: {handle.text()}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
