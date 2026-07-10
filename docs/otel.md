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
provider.add_span_processor(IntrospectionSpanProcessor())
```

Framework-specific instrumentors are experimental.

## Environment variables (OTel)

```shell
export INTROSPECTION_BASE_OTEL_URL="https://otel.introspection.dev" # optional
export INTROSPECTION_SERVICE_NAME="my-service"                      # optional
```
