# OpenTelemetry: analytics events & tracing

The Introspection API (`IntrospectionClient` / `AsyncIntrospectionClient` —
runtimes, tasks, files, conversations) is the SDK's primary surface and needs
no OpenTelemetry. This page covers the two **optional** OTel-based surfaces,
both behind the `[otel]` extra:

```shell
pip install 'introspection-sdk[otel]'
```

1. **Analytics events** (`track` / `feedback` / `identify`) via `IntrospectionLogs`.
2. **Traces** (span processors + LLM-framework instrumentors) via
   `introspection_sdk.init()` and the individual processors.

They are independent of each other and of the Introspection API — construct
only what you need.

---

## 1. Analytics events (track, feedback, identify) with `IntrospectionLogs`

```python
from introspection_sdk import IntrospectionLogs

logs = IntrospectionLogs(
    token="intro_xxx",        # or env: INTROSPECTION_TOKEN
    service_name="my-service",
    base_url="https://otel.introspection.dev",  # or env: INTROSPECTION_BASE_OTEL_URL
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

---

## 2. Traces (span processors + instrumentors) with `IntrospectionSpanProcessor`

Install the `[otel]` extra plus your framework extras of choice (or `[all]`):

```shell
pip install 'introspection-sdk[otel,anthropic,gemini,openai-agents,claude-agent,langchain]'
```

### Auto-wired via `init()` — recommended

`introspection.init()` detects every supported LLM framework you have installed
and wires them all into a single trace pipeline:

```python
import introspection_sdk as introspection

introspection.init()  # token from INTROSPECTION_TOKEN

# ...use Anthropic, Gemini, OpenAI Agents, Claude Agent, Logfire as usual —
# their calls are now traced automatically.
```

Auto-detected frameworks: Anthropic SDK, Google Gemini (`google-genai`), OpenAI
Agents SDK, Claude Agent SDK, Logfire / OpenInference (configure Logfire before
`init()`), and LangChain / LangGraph (attach `get_handler()` — see below).

LangChain callbacks are per-invoke, so `init()` prepares the handler and you
attach it:

```python
import introspection_sdk as introspection
from introspection_sdk.integrations.langchain import get_handler

introspection.init()
response = model.invoke("Hello!", config={"callbacks": [get_handler()]})
```

After `init()`, the module-level `introspection.track()` /
`introspection.feedback()` / `introspection.identify()` shortcuts proxy to the
global `IntrospectionLogs`.

### Manual / advanced setup

`init()` is the recommended entry point, but the individual processors and
instrumentors remain fully supported for custom wiring (sharing a
`TracerProvider`, dual-export, testing). See [`advanced.md`](advanced.md) for
opting out of auto-discovery, passing your own provider, standalone processor
construction, and testing with an in-memory exporter.

> See [`examples/`](../examples/) for complete integration patterns including
> dual-export with Arize, Langfuse, Braintrust, and LangSmith.

## Environment variables (OTel)

```shell
export INTROSPECTION_BASE_OTEL_URL="https://otel.introspection.dev" # optional
export INTROSPECTION_SERVICE_NAME="my-service"                      # optional
```
