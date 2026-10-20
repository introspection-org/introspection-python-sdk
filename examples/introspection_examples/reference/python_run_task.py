"""Python SDK reference: run a task, stream it, then send a follow-up turn.

Backs the "Run a task" block of the docs' Python SDK page (region
``reference/python/run-task``). The snippet is a whole program, so this
module runs it at import: start it with the command below, not by
importing it.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run -m introspection_examples.reference.python_run_task

The task runs on the ``support-agent`` runtime, as on the docs page; deploy
a runtime with that slug in the token's project first. When the project has
no such runtime the module prints a skip message and exits 0, so the
examples workflow can list it either way.

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

import os

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient, NotFoundError

load_dotenv()
if not os.getenv("INTROSPECTION_TOKEN"):
    raise SystemExit(
        "INTROSPECTION_TOKEN is not set: export a project API key "
        "(intro_...) or add it to .env"
    )
_probe = IntrospectionClient()
try:
    _probe.runtimes.resolve("support-agent")
except NotFoundError:
    print(
        "skipping: no support-agent runtime in this token's project; "
        "deploy one to run this example"
    )
    raise SystemExit(0) from None
finally:
    _probe.shutdown()

# The docs' line lengths, not the formatter's.
# fmt: off
# #region docs:reference/python/run-task
import asyncio

from introspection_sdk import AsyncIntrospectionClient
from introspection_sdk.schemas.agui import TextMessageContentEvent


async def main() -> None:
    async with AsyncIntrospectionClient() as client:
        runner = await client.runtimes("support-agent").run(identity={"user_id": "user_123"})
        async with runner:
            run = await runner.tasks.start(prompt="Summarize my open tickets.")
            async for event in run.stream():
                if isinstance(event, TextMessageContentEvent):
                    print(event.delta or "", end="")

            follow_up = await runner.tasks.runs.create(
                str(run.run.task_id), kind="prompt", prompt={"text": "Now draft the reply."}
            )
            print(await follow_up.text())


asyncio.run(main())
# #endregion docs:reference/python/run-task
# fmt: on
