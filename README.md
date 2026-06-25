<div align="center">
  <a href="https://introspection.dev">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.svg">
      <img alt="Introspection" src=".github/images/logo-light.svg" width="30%">
    </picture>
  </a>
</div>

<h4 align="center">Build frontier AI systems that self-improve.</h4>

<div align="center">
  <a href="https://introspection.dev"><img src="https://img.shields.io/badge/website-introspection.dev-blue" alt="Website"></a>
  <a href="https://pypi.org/project/introspection-sdk/"><img src="https://img.shields.io/pypi/v/introspection-sdk?label=%20" alt="PyPI version"></a>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
  <a href="https://x.com/IntrospectionAI"><img src="https://img.shields.io/twitter/follow/IntrospectionAI" alt="Follow on X"></a>
</div>

<br>

[Introspection](https://introspection.dev) continuously improves your AI systems with production feedback and frontier practices. This is the Python SDK.

## Install

```shell
uv add introspection-sdk
# or
pip install introspection-sdk
```

The default install is everything you need for the Introspection API
(runtimes, tasks, files, conversations) — no OpenTelemetry pulled in. To also
emit analytics events and export traces, add the `[otel]` extra; see
[**OpenTelemetry**](#opentelemetry-analytics--tracing) below.

## Introspection API (runtimes, tasks, files)

The main Introspection API. Open a `Runner` against a runtime, spawn tasks, and
stream their output; manage `files` and read `conversations` on the same Runner.
`AsyncIntrospectionClient` is the recommended entry point — everything that
touches the network is awaitable, and run output streams with `async for`:

```python
import asyncio

from introspection_sdk import AsyncIntrospectionClient


async def main() -> None:
    async with AsyncIntrospectionClient() as client:  # token from INTROSPECTION_TOKEN
        runner = await client.runtimes("customer-agent").run()

        async with runner:
            run = await runner.tasks.start(prompt="Say hello in one sentence.")

            async for event in run.stream():
                print(event.model_dump_json(by_alias=True, exclude_none=True))


asyncio.run(main())
```

A Runner exposes three DP-bound namespaces side by side: `runner.tasks`,
`runner.files`, and the read-only `runner.conversations`. The conversations
namespace lists conversation summaries (`runner.conversations.list()`), loads
the latest LLM turn of a conversation as a Responses-API-style view
(`await runner.conversations.retrieve(conversation_id)`), and walks a
conversation's per-turn items (`runner.conversations.items.list(...)`).

Every `list()` returns an `AsyncPager`: `async for` it to stream every item
across pages (fetched lazily), or `await` it for the first page with its
envelope metadata (counts, cursors):

```python
# Stream every summary across all pages.
async for summary in runner.conversations.list(limit=20):
    response = await runner.conversations.retrieve(
        summary.conversation_id or summary.trace_id
    )
    if response is not None:
        print(response.model, len(response.input_messages))

# Or just the first page, with totals.
first = await runner.files.list(include_total=True)
print(first.total_count, len(first.records))
```

See [`examples/api/async_runtimes.py`](examples/introspection_examples/api/async_runtimes.py)
for an end-to-end walkthrough.

### Service-account (machine) auth

A long-lived `INTROSPECTION_TOKEN` is the simplest credential. For headless /
CI callers that should not ship a static key, authenticate as a confidential
**service-account** Application instead — `from_service_account` mints a
short-lived, project-scoped token via the OAuth `client_credentials` grant and
wires it in, so the runtime flow is unchanged:

```python
from introspection_sdk import IntrospectionClient

client = IntrospectionClient.from_service_account(
    client_id="intro_app_…",      # confidential Application
    client_secret="intro_sk_…",   # minted once, kept server-side
    project="my-project",         # slug or UUID; the token is project-scoped
)
runner = client.runtimes("customer-agent").run()
```

The token is not auto-refreshed — re-mint once it expires
(`AsyncIntrospectionClient.from_service_account` is the awaitable twin).

When you're a **server broker** handing credentials to a browser client, mint
the token directly to also read `dp_url` (the Data Plane endpoint the Control
Plane resolved for the project) and resolve the runtime slug to a concrete
`runtime_id` — return `{ token, runtime_id, dp_url }` so the browser SDK talks
to the Data Plane without a hardcoded URL:

```python
from introspection_sdk import IntrospectionClient, service_account_token

token = service_account_token(
    client_id="intro_app_…",
    client_secret="intro_sk_…",
    project="my-project",
)
client = IntrospectionClient(token=token.access_token)
runtime = client.runtimes.resolve("customer-agent")
# -> hand { token.access_token, runtime.id, token.dp_url } to the browser
```

`token_exchange` (RFC 8693 partner-IdP federation) and
`authorization_code_token` (PKCE hosted-login callback) are the matching
server-side helpers for end-user auth — each returns the same `OAuthToken`
shape, carrying `dp_url`. See
[`examples/api/service_account.py`](examples/introspection_examples/api/service_account.py).

### Sync client

Not on `asyncio`? `IntrospectionClient` is the synchronous twin with an
identical surface — drop the `await`s, use `for` instead of `async for`, and
`with` instead of `async with` ([`examples/api/runtimes.py`](examples/introspection_examples/api/runtimes.py)):

```python
from introspection_sdk import IntrospectionClient

client = IntrospectionClient()  # token from INTROSPECTION_TOKEN
runner = client.runtimes("customer-agent").run()

run = runner.tasks.start(prompt="Say hello in one sentence.")
for event in run.stream():
    print(event.model_dump_json(by_alias=True, exclude_none=True))

runner.close()
client.shutdown()
```

## OpenTelemetry (analytics & tracing)

Two optional OTel-based surfaces live behind the `[otel]` extra, independent of
the Introspection API above:

```shell
pip install 'introspection-sdk[otel]'
```

- **Analytics events** — `track` / `feedback` / `identify` via `IntrospectionLogs`.
- **Traces** — auto-instrument Anthropic, Gemini, OpenAI Agents, Claude Agent,
  LangChain, and Logfire with a single `introspection_sdk.init()`.

Both are documented in [**`docs/otel.md`**](docs/otel.md); advanced/manual
wiring lives in [`docs/advanced.md`](docs/advanced.md). For complete
integration patterns (including dual-export with Arize, Langfuse, Braintrust,
and LangSmith) see [`examples/`](./examples/).

## Environment variables

```shell
# Introspection API (IntrospectionClient / AsyncIntrospectionClient)
export INTROSPECTION_TOKEN="intro_xxx"
export INTROSPECTION_BASE_API_URL="https://api.introspection.dev"   # optional
# The project is scoped by the API key. Pass project per call only to override
# it with a slug or UUID.

# OTel (IntrospectionLogs + span processors + instrumentors) — see docs/otel.md
export INTROSPECTION_BASE_OTEL_URL="https://otel.introspection.dev" # optional
export INTROSPECTION_SERVICE_NAME="my-service"                      # optional
```

## Documentation

Full documentation is available at [docs.introspection.dev](https://docs.introspection.dev).

## License

Apache-2.0
