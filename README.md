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

The default install is REST-only — no OpenTelemetry pulled in. Add the `[otel]` extra to enable analytics events and trace export:

```shell
pip install 'introspection-sdk[otel]'
```

### Optional extras

Per-framework convenience installs (`init()` auto-detects frameworks however
they were installed — these are just one-command setup):

```shell
pip install 'introspection-sdk[anthropic]'      # Anthropic SDK
pip install 'introspection-sdk[gemini]'         # Google Gemini (google-genai)
pip install 'introspection-sdk[openai-agents]'  # OpenAI Agents SDK
pip install 'introspection-sdk[claude-agent]'   # Claude Agent SDK
pip install 'introspection-sdk[langchain]'      # LangChain / LangGraph
pip install 'introspection-sdk[logfire]'        # Logfire
pip install 'introspection-sdk[all]'            # Everything above
```

## Three independent surfaces

The Python SDK exposes three surfaces you can adopt independently:

1. **Introspection API (runtimes, tasks, files, conversations)** with `IntrospectionClient` — the main Introspection API. Zero OpenTelemetry imports. Always available.
2. **Analytics events (track, feedback, identify)** with `IntrospectionLogs` — OTel logs exporter with baggage helpers. Owns its own `LoggerProvider`. Lives at `introspection_sdk.IntrospectionLogs`. Requires the `[otel]` extra.
3. **Traces (span processors + instrumentors)** with `IntrospectionSpanProcessor` and friends — `IntrospectionTracingProcessor`, `ClaudeTracingProcessor`, the LangChain callback handler, `AnthropicInstrumentor`, `GeminiInstrumentor`. Plus the `introspection_sdk.init()` convenience that auto-wires every supported framework. All under `introspection_sdk.otel` (or the dedicated `introspection_sdk.integrations.langchain` subpath for the LangChain handler). Requires the `[otel]` extra.

## 1. Introspection API (runtimes, tasks, files) with `IntrospectionClient`

The main Introspection API surface. No OTel packages required — install just the SDK:

```shell
pip install introspection-sdk
```

```python
from introspection_sdk import IntrospectionClient

client = IntrospectionClient()  # token from INTROSPECTION_TOKEN

runner = client.runtimes("customer-agent").run()

run = runner.tasks.start(prompt="Say hello in one sentence.")

for event in run.stream():
    print(f"[{event.event}] {event.data}")

runner.close()
client.shutdown()
```

### Async

Prefer `asyncio`? `AsyncIntrospectionClient` is a drop-in async twin — everything that touches the network is awaitable, `list()` returns an `AsyncPager` you `await` (first page) or `async for` (stream all pages), and run streams are consumed with `async for`. Both clients are first-class; pick the one that fits your app:

```python
import asyncio

from introspection_sdk import AsyncIntrospectionClient


async def main() -> None:
    async with AsyncIntrospectionClient() as client:  # token from INTROSPECTION_TOKEN
        runner = await client.runtimes("customer-agent").run()
        async with runner:
            run = await runner.tasks.start(prompt="Say hello in one sentence.")
            async for event in run.stream():
                print(f"[{event.event}] {event.data}")


asyncio.run(main())
```

A Runner exposes three DP-bound namespaces side by side: `runner.tasks`, `runner.files`, and the read-only `runner.conversations`. The conversations namespace lists conversation summaries (`runner.conversations.list()`), loads the latest LLM turn of a conversation as a Responses-API-style view (`runner.conversations.retrieve(conversation_id)`), and walks a conversation's per-turn items (`runner.conversations.items.list(...)`).

Every `list()` returns a `Pager`: iterate it to stream every item across pages (fetched lazily), or call `.page()` for the first page with its envelope metadata (counts, cursors):

```python
# Stream every summary across all pages.
for summary in runner.conversations.list(limit=20):
    response = runner.conversations.retrieve(summary.conversation_id or summary.trace_id)
    if response is not None:
        print(response.model, len(response.input_messages))

# Or just the first page, with totals.
first = runner.files.list(include_total=True).page()
print(first.total_count, len(first.records))
```

See [`examples/api/runtimes.py`](examples/introspection_examples/api/runtimes.py) for an end-to-end walkthrough.

## 2. Analytics events (track, feedback, identify) with `IntrospectionLogs`

Install the SDK with the `[otel]` extra:

```shell
pip install 'introspection-sdk[otel]'
```

```python
from introspection_sdk import IntrospectionLogs

logs = IntrospectionLogs(
    token="intro_xxx",        # or env: INTROSPECTION_TOKEN
    service_name="my-service",
    base_url="https://otel.introspection.dev",  # or env: INTROSPECTION_BASE_OTEL_URL
    project_id="proj_…",      # or env: INTROSPECTION_PROJECT_ID — optional
)

with logs.identify("user_123", traits={"plan": "pro"}):
    with logs.conversation("conv_456", previous_response_id="msg_123"):
        logs.feedback("thumbs_up", comments="Great response!")

logs.track("checkout_completed", {"amount": 42})
logs.shutdown()
```

### Methods

| Method | Description |
| ------ | ----------- |
| `track(event, properties=)` | Track any user action |
| `feedback(type, **kwargs)` | Track feedback on AI responses |
| `identify(user_id, traits=)` | Associate a user with traits (context manager) |
| `flush(timeout_ms=30000)` | Flush pending events |
| `shutdown()` | Shutdown and flush |

### Context managers

| Method | Description |
| ------ | ----------- |
| `conversation(id?, previous_response_id?)` | Set conversation context |
| `with_user_id(id)` | Set user context |
| `with_agent(name, id?)` | Set agent context |
| `with_anonymous_id(id)` | Set anonymous ID |
| `with_baggage(**values)` | Set arbitrary baggage values |

## 3. Traces (span processors + instrumentors) with `IntrospectionSpanProcessor`

Install the SDK with the `[otel]` extra plus your framework extras of choice (or `[all]`):

```shell
pip install 'introspection-sdk[otel,anthropic,gemini,openai-agents,claude-agent,langchain]'
```

### Auto-wired via `init()` — recommended

`introspection.init()` detects every supported LLM framework you have installed and wires them all into a single trace pipeline:

```python
import introspection_sdk as introspection

introspection.init()  # token from INTROSPECTION_TOKEN

# ...use Anthropic, Gemini, OpenAI Agents, Claude Agent, Logfire as usual —
# their calls are now traced automatically.
```

Auto-detected frameworks: Anthropic SDK, Google Gemini (`google-genai`), OpenAI Agents SDK, Claude Agent SDK, Logfire / OpenInference (configure Logfire before `init()`), and LangChain / LangGraph (attach `get_handler()` — see below).

LangChain callbacks are per-invoke, so `init()` prepares the handler and you attach it:

```python
import introspection_sdk as introspection
from introspection_sdk.integrations.langchain import get_handler

introspection.init()
response = model.invoke("Hello!", config={"callbacks": [get_handler()]})
```

After `init()`, the module-level `introspection.track()` / `introspection.feedback()` / `introspection.identify()` shortcuts proxy to the global `IntrospectionLogs`.

### Manual / advanced setup

`init()` is the recommended entry point, but the individual processors and instrumentors remain fully supported for custom wiring (sharing a `TracerProvider`, dual-export, testing). See [`docs/advanced.md`](docs/advanced.md) for opting out of auto-discovery, passing your own provider, standalone processor construction, and testing with an in-memory exporter.

> See [examples/](./examples/) for complete integration patterns including dual-export with Arize, Langfuse, Braintrust, and LangSmith.

## Environment variables

```shell
# Introspection API (IntrospectionClient)
export INTROSPECTION_TOKEN="intro_xxx"
export INTROSPECTION_BASE_API_URL="https://api.introspection.dev"   # optional
export INTROSPECTION_PROJECT_ID="proj_…"                            # optional

# OTel (IntrospectionLogs + span processors + instrumentors)
export INTROSPECTION_BASE_OTEL_URL="https://otel.introspection.dev" # optional
export INTROSPECTION_SERVICE_NAME="my-service"                      # optional
```

## Documentation

Full documentation is available at [docs.introspection.dev](https://docs.introspection.dev).

## License

Apache-2.0
