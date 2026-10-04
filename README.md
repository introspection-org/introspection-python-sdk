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

To record an app event under your own name (`ark.feed.entry`), use
`logs.log_event(name, attributes, event_id=...)`; `track` is an alias of it.
See [Logging custom events](docs/otel.md#logging-custom-events) for
idempotency, reserved names, use from a recipe sandbox, and reading events
back.

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

The runner also exposes `files`, `shares`, `events`, `metrics`, and
`automations`.

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

## Authenticate

An API key (`INTROSPECTION_TOKEN`) is the simplest credential. To issue tokens
yourself, register an Application in the project. Its type is chosen at
creation, cannot change, and gives it exactly one way in; an app that needs two
ways in registers two Applications.

| Type              | Who signs in                                         | Grants (`allowed_grants`)                     | SDK entry point                                                               |
| ----------------- | ---------------------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------- |
| `service_account` | Your server, with a `client_secret`                  | `client_credentials`                          | `IntrospectionClient.from_service_account(...)`, `service_account_token(...)` |
| `jwks`            | Your end users, through your own identity provider   | none: RFC 8693 token exchange of their JWT    | `token_exchange(...)`                                                         |
| `spa`             | Your end users, through Introspection's hosted login | `authorization_code` (PKCE), `refresh_token`  | `authorization_code_token(...)`                                               |
| `native`          | Your end users, with a code sent to their email      | `email_code`, `device_code`, `refresh_token`  | `EmailCodeAuth`, `AsyncEmailCodeAuth`                                         |

The server derives an Application's grants from its type; a client never sends
them. An `spa` needs at least one `redirect_uris` entry and a `jwks` takes none;
an `spa` with a brokered identity provider also exchanges that login's
`id_token` through `token_exchange`. Applications created before the types
became exclusive keep working as they did. Tokens for end users belong to a
`customer` member and carry at most the Application's `allowed_scopes`. A
`service_account` or `jwks` token is not refreshable: mint or exchange again
before `expires_in` lapses.

### Native email-code sign-in

```python
from introspection_sdk import EmailCodeAuth

auth = EmailCodeAuth(client_id="intro_app_...", project="ark")
auth.send_code("user@example.com")
auth.verify_code("user@example.com", code)  # six digits, or six letters and digits on a first sign-in

client = auth.client()  # Data Plane URL from the session
for event in client.events.list("introspection.feedback", limit=5):
    print(event.payload.name)
```

`EmailCodeAuth` refreshes the access token `leeway` seconds (default 60) before
it expires and after a `401`, and concurrent callers share one refresh. A
refresh the server rejects signs the user out and raises `AuthenticationError`.
A sign-in or refresh response that arrives after a newer sign-in or a sign-out
is dropped and raises `SignInSupersededError`, so it never overwrites the newer
session. Pass `session=` to restore a saved `AuthSession` and
`on_session_change=` to persist each change (`None` after `sign_out()`); the
session holds the refresh token, so store it as a secret. A rate-limited
`send_code` raises `RateLimitError` with `retry_after`.

The token is a Data Plane credential: Data Plane namespaces such as
`client.events` accept it within the Application's `allowed_scopes`, and
Control Plane namespaces such as `client.runtimes` reject it. `AsyncEmailCodeAuth` is the asyncio twin, and
`send_email_code`, `email_code_token`, `refresh_access_token` and
`revoke_session` are the one-shot calls underneath. See
[`examples/introspection_examples/api/native_email_code.py`](examples/introspection_examples/api/native_email_code.py).

## Schedule automations

`client.automations` manages a project's automations on the data plane: a
prompt on a schedule (`kind=None`), or platform work (`observation_synthesis`,
`observation_clustering`, `project_check_in`). A prompt automation creates a
task per firing, or posts into an existing task when it names `task_id`. A
one-off reminder is a `manual` automation with a future `next_trigger_at`:

```python
from datetime import UTC, datetime

from introspection_sdk.schemas.automations import AutomationMetadata

reminder = client.automations.create(
    name="Friday check-in",
    trigger_type="manual",
    prompt="How did the week go?",
    runtime_group_id=runtime_group_id,
    task_id=task_id,
    next_trigger_at=datetime(2026, 10, 9, 16, tzinfo=UTC),
)

weekly = client.automations.create(
    name="Weekly digest",
    trigger_type="cron",
    cron_schedule="0 9 * * 1",
    prompt="Summarize my week",
    runtime_group_id=runtime_group_id,
    metadata=AutomationMetadata(timezone="Europe/London"),
)

for automation in client.automations.list(enabled=True, scheduled=True):
    print(automation.name, automation.kind, automation.next_trigger_at)

client.automations.update(weekly.id, enabled=False)  # pause, keep the slot
result = client.automations.trigger(weekly.id)       # run it now
print(result.status, result.task_id, result.reason)
```

`update` sends only the fields you pass, so `None` never clears anything;
`metadata` replaces wholesale, and `kind` / `trigger_type` are immutable.
`delete` soft-deletes, except for a project default, which answers 409:
disable it instead. `kind`, `trigger_type`, condition types, skip reasons and
trigger statuses are open enums: a value this SDK does not know yet decodes
as a plain string rather than failing.

Each firing is recorded as an event, read like any other family:

```python
for event in client.events.list(
    "introspection.automation.triggered", automation_id=weekly.id
):
    print(event.payload.slot, event.payload.task_id, event.payload.posted)
```

`introspection.automation.skipped` records a scheduled slot that ran nothing,
with its `reason`; it is project-owned, so only callers with project-wide
telemetry access read it. Both families take the `automation_id` and
`task_id` filters.

Today the server serves `/v1/automations` to project administrators only and
answers anyone else with a 403. introspection-cloud#3137 (not yet shipped)
opens the routes to members for their own automations that post into one of
their own tasks, and adds the `task_id` list filter, which this SDK already
sends.

`runner.automations` is the same namespace on a Runner, sending the
runner's token. The routes need the `automations:read` and
`automations:write` scopes, so a `native` sign-in cannot use them yet.
`can_manage` says whether the caller may change an automation, and
`created_by_member_id` who created it.

## Environment variables

```shell
export INTROSPECTION_TOKEN="intro_xxx"
export INTROSPECTION_BASE_API_URL="https://api.introspection.dev"  # optional
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

`run.stream()` and `run.text()` (and `tasks.runs.stream(task_id, run_id)`)
recover from a dropped connection on their own. They follow the cross-SDK
recovery contract, pinned by the shared `run-stream-contract.json` fixtures.

- **Cursor.** The first attach sends `Last-Event-ID: 0`, so output produced
  before it is replayed. Every reconnect resumes from the last content cursor:
  the id of the last new content frame.
- **Completion.** Only a settling `RUN_FINISHED` or `RUN_ERROR` confirms that
  the run ended. A `RUN_FINISHED` whose `result.reason` is `"stream_close"`
  only ends an attach, so it is not yielded.
- **Clean EOF.** When the stream closes without a settling event, the SDK
  reads that run's status (`GET /v1/tasks/{task_id}/runs/{run_id}`).
  `failed` or `cancelled` raises `RunFailedError`. `idle`, `completed` or
  `awaiting_user` raises `StreamIncompleteError`, because the run settled
  without the stream confirming it. Anything else, including a status read
  that fails, reconnects.
- **Budget.** Reconnects are bounded by `max_reconnects` (default 5) and
  `timeout` (default 300 s), with backoff from `backoff` (default 0.5 s). A new
  content cursor renews both, so a long run keeps a full recovery window.
  Duplicate content, lifecycle events and heartbeats renew neither. The timeout
  is checked only before a reconnect, never while a connection is open. A
  `429` while the run is not attachable yet waits for `Retry-After` within the
  timeout and does not spend the reconnect budget.
- **Past the replay buffer.** When the cursor is older than what the runtime
  retains, the reconnect answers with one AG-UI `MESSAGES_SNAPSHOT` of the run's
  messages so far. Its id becomes the new cursor, and `text()` replaces the
  assistant text it had collected with the snapshot's. When the runtime holds
  neither the frames nor a snapshot, it answers `410` and the stream raises
  `StreamIncompleteError`. Runtime images older than the snapshot send a
  `CUSTOM resume_gap` event instead: `stream()` yields it, and `text()` raises
  `StreamIncompleteError`.
- **`text()`** never returns partial output. It raises `RunFailedError` on
  `RUN_ERROR` and `StreamIncompleteError` wherever output may be missing. The
  SDK does not read the conversation transcript to fill a gap (and does not need
  the `conversations:read` scope to stream); read it yourself with
  `runner.conversations` when you need the output after such an error.

Use a concrete run id for one turn. `runs/current` is a moving alias, so a
reconnect or status read can resolve to the next run.

The in-process fake sandbox (`mock://`) delivers replies only through the
conversation transcript. Its stream ends with an attach-level `stream_close`,
which `text()` cannot treat as a completed reply, so test fake runs through
transcript reads and `text()` against a real runtime.

Each SDK's test suite pins the fixture's SHA-256; a contract change updates all
four copies (Swift, JavaScript, Rust, Python) and their hashes together.
`StreamIncompleteError` and `RunFailedError` are exported from
`introspection_sdk` for both the sync and async clients.

## License

Apache-2.0
