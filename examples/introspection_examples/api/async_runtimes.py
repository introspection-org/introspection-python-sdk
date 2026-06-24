"""End-to-end async Runner walkthrough — the async twin of
``introspection_examples.api.runtimes``.

Resolve a runtime by name, open an :class:`AsyncRunner` against it, spawn
a task, and stream its run — all on :mod:`asyncio` with non-blocking IO,
mirroring the TypeScript SDK's async-by-default Runner.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.async_runtimes

Optional env:
    INTROSPECTION_RUNTIME_NAME  - runtime to resolve (default: customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import asyncio
import os

from introspection_sdk import AsyncIntrospectionClient
from introspection_sdk.version import VERSION


async def main() -> None:
    runtime_name = os.getenv("INTROSPECTION_RUNTIME_NAME", "customer-agent")

    # ``async with`` tears the client's HTTP pool down deterministically.
    async with AsyncIntrospectionClient() as client:
        runner = await client.runtimes(runtime_name).run(
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

        async with runner:
            run = await runner.tasks.start(prompt="Say hello in one sentence.")
            task_id = run.task.id if run.task else None
            print(f"spawned task={task_id}, run={run.run.id}")

            # `async for` over the SSE stream — frames arrive without
            # blocking the event loop.
            async for event in run.stream():
                print(event.model_dump_json(by_alias=True, exclude_none=True))

            # Once the run has drained, the task carries its conversation id
            # in metadata. Fetch that conversation, then mint a read-share —
            # the grant's `url` (carrying the `?share_id` capability) is what
            # you hand out, or feed back as `fork_share_id` to branch a new
            # task off this conversation.
            conversation_id = (
                (run.task.metadata or {}).get("conversation_id")
                if run.task
                else None
            )
            if conversation_id:
                response = await runner.conversations.retrieve(conversation_id)
                if response is not None:
                    print(
                        f"completed conversation {conversation_id}: "
                        f"model={response.model}, "
                        f"{len(response.output_messages)} output message(s)"
                    )
                share = await runner.shares.create(
                    resource_type="conversation",
                    resource_id=conversation_id,
                )
                print(f"shared conversation -> {share.url}")
                # Branch a fresh task off the shared conversation's history:
                #   await runner.tasks.create(
                #       prompt="continue", fork_share_id=str(share.id))

            file = await runner.files.create_text(
                name="notes.md",
                content="# Hello\n\nFrom the async Python SDK.",
                mime_type="text/markdown",
            )
            print(f"created file: {file.id}")

            payload = await runner.files.download(str(file.id))
            print(f"downloaded {len(payload)} bytes")

            binary = await runner.files.upload(
                file=b"hello binary",
                name="hello.bin",
                file_type="upload",
            )
            print(f"uploaded binary file: {binary.id}")

            # `list()` returns an AsyncPager: `await` it for the first page
            # with its envelope metadata, or `async for` it to stream every
            # item across pages.
            files_page = await runner.files.list(include_total=True)
            print(f"total files: {files_page.total_count}")
            async for f in runner.files.list():
                print(f"  file {f.id} ({f.name})")

            # Read-only conversations namespace: list recent conversations,
            # then load the latest LLM turn of one as a Responses-API-style
            # view and walk its per-turn transcript.
            convos_page = await runner.conversations.list(limit=5)
            print(
                "recent conversations (first page): "
                f"{len(convos_page.records)}"
            )
            if convos_page.records:
                summary = convos_page.records[0]
                cid = summary.conversation_id or summary.trace_id
                response = await runner.conversations.retrieve(cid)
                if response is not None:
                    print(
                        f"latest turn of {cid}: model={response.model}, "
                        f"{len(response.input_messages)} input message(s)"
                    )
                async for item in runner.conversations.items.list(
                    cid, order="asc"
                ):
                    print(f"  item {item.id} ({item.node_type})")


if __name__ == "__main__":
    asyncio.run(main())
