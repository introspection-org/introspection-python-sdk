# OpenTelemetry: analytics events & tracing

The Introspection API (`IntrospectionClient` / `AsyncIntrospectionClient` —
runtimes, tasks, files, conversations) is the SDK's primary surface and needs
no OpenTelemetry. This page covers the two **optional** OTel-based surfaces,
both behind the `[otel]` extra:

```shell
pip install 'introspection-sdk[otel]'
```

1. **Analytics events** (`track` / `feedback` / `identify`) via `IntrospectionLogs`.
2. **Traces** via `IntrospectionSpanProcessor`.

They are independent of each other and of the Introspection API — construct
only what you need.

## Both at once: `init()`

```python
from introspection_sdk import otel as introspection

introspection.init(token="intro_xxx", service_name="my-service")

with introspection.conversation() as conversation_id:
    with introspection.with_user_id("user_123"):
        ...                                  # your gen_ai spans
        introspection.track("checkout_completed", {"amount": 42})

introspection.shutdown()                     # also runs at exit
```

`init()` attaches the span processor to a shared `TracerProvider` (yours if you
pass `tracer_provider=`, otherwise the global one) and builds the logs stream
behind `track` / `feedback` / `identify`. It returns the provider and is
idempotent; `shutdown()` flushes both and clears the state so a later `init()`
reconfigures.

The `with_*` context managers (`with_agent`, `with_conversation`,
`with_user_id`, `with_anonymous_id`) scope OTel baggage that both surfaces
read, so anything set inside the block lands on the events *and* on the spans.

---

## 1. Analytics events (track, feedback, identify) with `IntrospectionLogs`

```python
from introspection_sdk import IntrospectionLogs

logs = IntrospectionLogs(
    token="intro_xxx",        # or env: INTROSPECTION_TOKEN
    service_name="my-service",
    base_otel_url="https://otel.introspection.dev",  # or env: INTROSPECTION_BASE_OTEL_URL
)

logs.identify("user_123", traits={"plan": "pro"})

with logs.set_user_id("user_123"):
    with logs.set_conversation("conv_456", previous_response_id="msg_123"):
        logs.feedback("thumbs_up", comments="Great response!")

logs.track("checkout_completed", {"amount": 42})
logs.shutdown()
```

### Methods

| Method | Description |
| ------ | ----------- |
| `track(event, properties=)` | Track any user action |
| `feedback(type, **kwargs)` | Track feedback on AI responses |
| `identify(user_id, traits=)` | Associate a user with traits |
| `flush(timeout_ms=30000)` | Flush pending events |
| `shutdown()` | Shutdown and flush |

### Context managers

| Method | Description |
| ------ | ----------- |
| `set_conversation(id?, previous_response_id?)` | Set conversation context |
| `set_user_id(id)` | Set user context |
| `set_agent(name, id?)` | Set agent context |
| `set_anonymous_id(id)` | Set anonymous ID |
| `set_baggage(**values)` | Set arbitrary baggage values |

---

## 2. Traces with `IntrospectionSpanProcessor`

Install the `[otel]` extra:

```shell
pip install 'introspection-sdk[otel]'
```

Construct the processor directly when you own the provider:

```python
from opentelemetry.sdk.trace import TracerProvider
from introspection_sdk import IntrospectionSpanProcessor

provider = TracerProvider()
provider.add_span_processor(IntrospectionSpanProcessor(token="intro_xxx"))
```

The SDK ships no framework instrumentors. Emit `gen_ai.*` spans yourself (or
from whatever library already emits them) and the processor exports them.

**Only LLM spans are exported.** A span reaching the processor without any of
`gen_ai.provider.name`, `gen_ai.operation.name`, `gen_ai.request.model`,
`gen_ai.input.messages`, or `gen_ai.output.messages` is dropped — the processor
usually sits on the global provider, where every HTTP and framework span in the
process also arrives.

On the spans it does export, the processor:

- stamps `gen_ai.conversation.id` (baggage wins, then an existing attribute,
  then a stable per-trace id),
- stamps `gen_ai.agent.name` / `gen_ai.agent.id` and
  `identity.user.id` / `identity.anonymous.id` from baggage, so a scope set
  with the `with_*` managers reaches the trace,
- defaults `gen_ai.operation.name` to `"chat"` when messages are present,
- drops the deprecated `gen_ai.system` key in favour of `gen_ai.provider.name`.

`Attr` carries the Introspection-namespaced key names for hand-written
instrumentation: `Attr.TERMINATION_REASON` (`"cancelled"` alongside
`gen_ai.response.finish_reasons=["aborted"]` and an Unset status is how a
requested abort reads as an outcome rather than a failure) and
`Attr.LLM_COST_USD` / `Attr.LLM_UPSTREAM_COST_USD` for provider-reported cost.

## Environment variables (OTel)

```shell
export INTROSPECTION_BASE_OTEL_URL="https://otel.introspection.dev" # optional
export INTROSPECTION_SERVICE_NAME="my-service"                      # optional
```
