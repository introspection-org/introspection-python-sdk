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

### Endpoint-binding proxy transports

The default install includes the native `httpx2` adapter:

```python
from introspection_sdk.proxy.httpx2 import IntrospectionTransport
```

Libraries that still use legacy `httpx`, including current Harbor and E2B
releases, can opt into that dependency and import the matching adapter:

```shell
pip install "introspection-sdk[proxy-httpx]"
```

```python
from introspection_sdk.proxy.httpx import IntrospectionTransport
```

Both imports use the same routing implementation and the
`INTROSPECTION_EGRESS_URL`, `INTROSPECTION_ENDPOINT_HOSTS`, and standard proxy
environment contract. Transport types cannot be shared between the two HTTP
libraries, so only their thin library-specific wrappers differ.

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

client = IntrospectionClient(
    token=member_access_token,
    cp_session=encoded_member_session,
    base_api_url="https://api.introspection.dev",
    dp_url="https://dp.example",
)

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

## Browse repositories

`client.repositories` lists the Git repositories linked to a project and reads
their contents at one resolved commit through the data plane:

```python
repo = client.repositories.list(slug="acme/support")[0]

for entry in client.repositories.contents(repo.id, "agents", ref="main"):
    print(entry.type, entry.path)

readme = client.repositories.contents.get(repo.id, "README.md")
print(readme.type, readme.commit_sha)
```

Iterating `contents()` follows the page cursor; `contents.get()` returns a
`RepositoryDirectory` page or a `RepositoryFile`, discriminated on `type`.

History pages the same way, and one commit carries its changed files and diff:

```python
for commit in client.repositories.commits(repo.id, sha="main", path="agents"):
    print(commit.sha[:7], commit.message.splitlines()[0])

detail = client.repositories.commit(repo.id, commit.sha)
print([f.filename for f in detail.files], len(detail.patch))
```

Merging mirrors GitHub's merges API: `head` is a branch or a full commit sha,
and `None` means `base` already contains it. A conflict raises
`ConflictError` with nothing changed.

```python
merge = client.repositories.merges.create(repo.id, "main", "feature")
if merge is not None:
    print(merge.sha, merge.parents)
```

## Label members

`client.members` reads and updates the organization's members. Each carries
two label sets: `tags` are **access-bearing** (a member reaches every file and
task whose tags intersect its own, so writing them needs `members:manage`),
while `metadata` is a `key: value` map that **grants nothing** and exists to
filter on.

```python
for member in client.members.list(metadata={"plan": "enterprise"}, tag="team:acme"):
    print(member.id, member.metadata)

member = client.members.update(member_id, metadata={"plan": "pro", "region": "eu"})
client.members.update(member_id, metadata={})  # clear it
```

`update` replaces `tags` and `metadata` wholesale: omit a field to leave it,
pass `[]` / `{}` to clear it. The `metadata` filter ANDs up to 16 pairs with
distinct keys, each matched exactly. Keys are letters, digits, `_` and `-`
(no `.`); values are non-empty strings; one write carries at most 64 entries. The
server answers 422 otherwise.

`create` invites a human by email and can seed both sets. A `customer` member
is minted from an asserted identity instead, and that identity can label it:

```python
runner = client.runtimes("customer-agent").run(
    identity={"user_id": "u_123", "metadata": {"plan": "enterprise"}},
)
```

Identity `metadata` seeds a new member and is merged into an existing one,
overwriting keys of the same name (including ones an admin set) and keeping
the rest; `refresh()` re-sends it. Identity `tags`, by contrast, apply only
when the member is created.

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

## Stream recovery

Run streams request replay from cursor `0`, including output produced before the
first connection. Only a settling `RUN_FINISHED` or `RUN_ERROR` confirms completion;
`RUN_FINISHED` with `result.reason = "stream_close"` is suppressed. A nonterminal
EOF checks the specific run's status and reconnects within the recovery budget.
Each new content cursor renews both the timeout window and the reconnect budget.
Lifecycle events, heartbeats and duplicate content renew neither. The timeout is
checked when recovery is needed; it does not interrupt an open connection.

Every reconnect resumes from the last content cursor (`Last-Event-ID`). When
that cursor is older than the server's replay buffer, the stream continues with
one AG-UI `MESSAGES_SNAPSHOT` holding the run's messages so far; its id becomes
the new cursor, and the text helper takes its assistant text in place of what it
had read. When the server holds neither the frames nor a snapshot, it answers
`410` and the stream ends with an incomplete-output error. Runtime images that
predate the snapshot send `CUSTOM resume_gap` instead; raw streams pass it
through. The text helper raises an incomplete-output error instead of returning
partial text, including on `resume_gap`; it also raises on run failure or
cancellation. If the status read
says the run settled but the stream never confirmed completion, it raises an
incomplete-output error. Recover final output from the conversation transcript
when needed; the SDK does not automatically hydrate it or require an additional
`conversations:read` scope just to stream. A long stream can therefore
reconnect after its original timeout as long as content has continued to advance.

Use a concrete run ID when consuming one turn. `runs/current` is a moving alias: a
reconnect or status read may resolve to the next turn if another run has started.

The in-process fake sandbox (`mock://`) supplies replies through the conversation
transcript, not SSE. Its attach-only `stream_close` cannot satisfy `.text()`; use
transcript reads for fake-sandbox tests, or a real runtime for `.text()` tests.

The shared `run-stream-contract.json` fixtures pin these behaviors across Swift,
JavaScript, Rust and Python. Each test suite pins the fixture SHA-256; intentional
contract changes must update all four copies and their expected hashes together.

Python exports `StreamIncompleteError` and `RunFailedError` from `introspection_sdk`, for both sync and async clients.

## License

Apache-2.0
