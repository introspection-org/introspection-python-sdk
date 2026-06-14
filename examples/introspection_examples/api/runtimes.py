"""End-to-end Runner walkthrough — resolve a runtime by name, open a
Runner against it, spawn a task, stream its run.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.runtimes

Optional env:
    INTROSPECTION_RUNTIME_NAME  - runtime to resolve (default: customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os

from introspection_sdk import IntrospectionClient
from introspection_sdk.version import VERSION


def main() -> None:
    client = IntrospectionClient()

    runtime_name = os.getenv("INTROSPECTION_RUNTIME_NAME", "customer-agent")

    runner = client.runtimes(runtime_name).run(
        identity={"user_id": "u_42"},
        caller={
            "ip": "8.8.8.8",
            "user_agent": f"introspection-sdk-python/{VERSION}",
            "library": {
                "name": "introspection-sdk-python",
                "version": VERSION,
            },
        },
    )
    print(f"runner -> dp={runner.dp_endpoint}, ctx={runner.context}")

    try:
        run = runner.tasks.start(prompt="Say hello in one sentence.")
        task_id = run.task.id if run.task else None
        print(f"spawned task={task_id}, run={run.run.id}")

        for event in run.stream():
            print(f"[{event.event}] {event.data}")

        file = runner.files.create_text(
            name="notes.md",
            content="# Hello\n\nFrom the Python SDK.",
            mime_type="text/markdown",
        )
        print(f"created file: {file.id}")

        payload = runner.files.download(str(file.id))
        print(f"downloaded {len(payload)} bytes")

        binary = runner.files.upload(
            file=b"hello binary",
            name="hello.bin",
            file_type="upload",
        )
        print(f"uploaded binary file: {binary.id}")

        files_page = runner.files.list()
        print(f"total files (first page): {len(files_page.records)}")

        # Read-only conversations namespace: list recent conversations,
        # then load the latest LLM turn of one as a Responses-API-style
        # view and walk its per-turn transcript.
        convos_page = runner.conversations.list(limit=5)
        print(f"recent conversations (first page): {len(convos_page.records)}")
        if convos_page.records:
            summary = convos_page.records[0]
            cid = summary.conversation_id or summary.trace_id
            response = runner.conversations.retrieve(cid)
            if response is not None:
                print(
                    f"latest turn of {cid}: model={response.model}, "
                    f"{len(response.input_messages)} input message(s)"
                )
            for item in runner.conversations.items.iter(cid, order="asc"):
                print(f"  item {item.id} ({item.node_type})")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
