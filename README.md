<div align="center">
  <a href="https://introspection.dev">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.svg">
      <img alt="Introspection" src=".github/images/logo-light.svg" width="30%">
    </picture>
  </a>
</div>

<h4 align="center">The infrastructure for long-horizon vertical agents.</h4>

<div align="center">
  <a href="https://introspection.dev"><img src="https://img.shields.io/badge/website-introspection.dev-blue" alt="Website"></a>
  <a href="https://pypi.org/project/introspection-sdk/"><img src="https://img.shields.io/pypi/v/introspection-sdk?label=%20" alt="PyPI version"></a>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
  <a href="https://x.com/IntrospectionAI"><img src="https://img.shields.io/twitter/follow/IntrospectionAI" alt="Follow on X"></a>
</div>

[Introspection](https://introspection.dev) is the infrastructure for
long-horizon vertical agents, powered by Pi. Define an agent as a
[Recipe](https://pi.recipes) — agents, skills, policies, and evals in plain
source you own in Git — deploy it to a governed per-customer Runtime, and
improve it in production with conversations, observations, judges, and
experiments.

This is the Python SDK: run tasks against a deployed runtime, stream their
output, and record what users thought of the result.

## Install

```shell
uv add introspection-sdk
# or
pip install introspection-sdk
```

## Run a task

```python
import asyncio

from introspection_sdk import AsyncIntrospectionClient


async def main() -> None:
    async with AsyncIntrospectionClient() as client:  # token from INTROSPECTION_TOKEN
        runner = await client.runtimes("customer-agent").run()

        async with runner:
            run = await runner.tasks.start(prompt="Say hello in one sentence.")

            async for event in run.stream():
                print(event)


asyncio.run(main())
```

Or wait for the finished answer instead of streaming:

```python
run = await runner.tasks.start(prompt="Summarize my open tickets.")
print(await run.text())
```

Continue the same task with a follow-up run:

```python
follow_up = await runner.tasks.runs.create(
    str(run.run.task_id),
    kind="prompt",
    prompt={"text": "Now draft the reply."},
)
print(await follow_up.text())
```

`IntrospectionClient` is the synchronous twin with the same surface — drop the
`await`s and use `for` instead of `async for`.

See [Tasks and streaming](https://docs.introspection.dev/sdk/python/tasks-and-streaming) for reconnects,
interrupts, and cancellation.

## Record feedback

Install the OpenTelemetry extra, then attach the outcome to the conversation
the agent produced:

```shell
pip install 'introspection-sdk[otel]'
```

```python
from introspection_sdk import IntrospectionLogs

logs = IntrospectionLogs(service_name="support-api")

with logs.identify("user_123", traits={"plan": "pro"}):
    with logs.set_conversation(conversation_id):
        logs.feedback("thumbs_up", comments="The answer solved it")

logs.track("case_closed", {"source": "web"})
logs.shutdown()
```

`feedback` records how a result landed, `track` records a product event, and
`identify` attaches who it was.

See [Product signals](https://docs.introspection.dev/sdk/python/product-signals) for the full surface, and
[**`docs/otel.md`**](docs/otel.md) for the OTel wiring.

## Read what happened

A finished task leaves a durable conversation. Add immutable, filter-only
metadata when creating the task, then use the same keys to find it later:

```python
await runner.tasks.create(
    prompt="Handle this checkout",
    conversation_metadata={"flow": "checkout", "tenant": "acme"},
)

async for summary in runner.conversations.list(
    limit=20,
    metadata={"flow": "checkout"},
):
    print(summary.id, summary.usage.total_tokens, summary.cost.usd)
```

The runner also exposes `files`, `shares`, `events`, and `metrics`.

## Curate traces with human review

Annotations are append-only events on an OTel trace/span. Each write changes
exactly one dimension; label and reviewer lists are complete snapshots, so an
empty list clears that dimension.

```python
from introspection_sdk import IntrospectionClient

client = IntrospectionClient(token="intro_xxx", dp_url="https://dp.example")

client.annotations.create(
    trace_id="0af7651916cd43dd8448eb211c80319c",
    span_id="b7ad6b7169203331",
    reviewer_emails=["expert@example.com"],
)
client.annotations.create(
    trace_id="0af7651916cd43dd8448eb211c80319c",
    span_id="b7ad6b7169203331",
    comment="The answer missed the governing exception.",
)

for item in client.annotations.list(label="needs-review"):
    print(item.trace_id, item.span_id, item.latest_comment)
```

Reusable labels live in `client.project_labels`; their slug and color are
immutable after creation, while the optional description can be updated.

See [Production evidence](https://docs.introspection.dev/sdk/python/production-evidence) for transcripts,
typed events, and metrics queries, [Files and shares](https://docs.introspection.dev/sdk/python/files-and-shares)
for durable inputs and grants, and [`examples/`](examples/introspection_examples/)
for end-to-end scripts.

## Environment variables

```shell
export INTROSPECTION_TOKEN="intro_xxx"
export INTROSPECTION_SERVICE_NAME="my-service"   # optional
export INTROSPECTION_LOG_LEVEL="debug"           # optional
```

## Documentation

- [Python quickstart](https://docs.introspection.dev/sdk/python/quickstart)
- [Tasks and streaming](https://docs.introspection.dev/sdk/python/tasks-and-streaming)
- [Files and shares](https://docs.introspection.dev/sdk/python/files-and-shares)
- [Production evidence](https://docs.introspection.dev/sdk/python/production-evidence)
- [Product signals](https://docs.introspection.dev/sdk/python/product-signals)
- [Platform operations](https://docs.introspection.dev/sdk/python/platform-operations)
- [Python SDK reference](https://docs.introspection.dev/sdk/python/reference)
- [Authentication](https://docs.introspection.dev/sdk/authentication)

## License

Apache-2.0
