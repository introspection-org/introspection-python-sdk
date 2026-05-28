"""End-to-end Runner walkthrough — find-or-create a runtime, open a
Runner against it, spawn a task, stream its run. Python sibling of the
Rust ``examples/tasks_files.rs`` example.

Run with:
    INTROSPECTION_TOKEN=intro_xxx
    INTROSPECTION_PROJECT_ID=<uuid>
    INTROSPECTION_RECIPE_ID=<uuid>
    INTROSPECTION_RUNTIME_NAME=<string, optional>  default: customer-agent

        uv run python examples/introspection_examples/tasks_files.py

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
from uuid import UUID

from introspection_sdk import IntrospectionClient
from introspection_sdk.schemas.runtimes import Runtime, RuntimeCreate
from introspection_sdk.version import VERSION


def ensure_runtime(
    client: IntrospectionClient,
    project_id: UUID,
    recipe_id: UUID,
    name: str,
) -> Runtime:
    """Find a runtime by ``name`` in the project; create+activate one
    pinned to ``recipe_id`` if none exists. Returns the row the rest of
    the example drives a runner against.
    """
    page = client.runtimes.list(
        project_id=str(project_id), name=name, only_active=True, limit=2
    )
    if page.records:
        return page.records[0]

    print(f"no existing runtime named {name!r}; creating one...")
    created = client.runtimes.create(
        RuntimeCreate(
            project_id=project_id,
            recipe_id=recipe_id,
            name=name,
            description="Created by the Python SDK tasks_files example",
        )
    )
    # Activate so subsequent `runtimes(name).run(...)` resolutions pick it up.
    return client.runtimes(created.id).activate(project_id=str(project_id))


def main() -> None:
    client = IntrospectionClient()

    project_id = UUID(os.environ["INTROSPECTION_PROJECT_ID"])
    recipe_id = UUID(os.environ["INTROSPECTION_RECIPE_ID"])
    runtime_name = os.getenv("INTROSPECTION_RUNTIME_NAME", "customer-agent")

    # 1) Find-or-create the runtime by name. CP requires a project_id +
    #    a recipe pin to create; subsequent runs in this script just
    #    reuse the active row.
    runtime = ensure_runtime(client, project_id, recipe_id, runtime_name)
    print(
        f"runtime -> {runtime.name} ({runtime.id}), active={runtime.is_active}"
    )

    # 2) Open a Runner against the runtime. CP /run mints a short-lived
    #    JWT and tells the runner which DP to talk to. `caller` is an
    #    optional segment.io-style observability payload — telemetry /
    #    report slicing only. Routing never reads it.
    runner = client.runtimes(runtime.id).run(
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
        # 3) Spawn a task on the runner (cursor-style sugar: one call
        #    creates the task and its first run) and stream its events.
        run = runner.tasks.start(prompt="Say hello in one sentence.")
        task_id = run.task.id if run.task else None
        print(f"spawned task={task_id}, run={run.run.id}")

        for event in run.stream():
            print(f"[{event.event}] {event.data}")

        # 4) Bonus — create a text file by content, then download it.
        file = runner.files.create_text(
            name="notes.md",
            content="# Hello\n\nFrom the Python SDK.",
            mime_type="text/markdown",
        )
        print(f"created file: {file.id}")

        payload = runner.files.download(str(file.id))
        print(f"downloaded {len(payload)} bytes")

        # 5) Multipart upload from in-memory bytes.
        binary = runner.files.upload(
            file=b"hello binary",
            name="hello.bin",
            file_type="upload",
        )
        print(f"uploaded binary file: {binary.id}")

        # 6) List files (single page envelope).
        files_page = runner.files.list()
        print(f"total files (first page): {len(files_page.records)}")
    finally:
        runner.close()
        client.shutdown()


if __name__ == "__main__":
    main()
