# Advanced setup

`introspection.init()` covers most cases. This page documents the lower-level
API for custom wiring. All of it remains supported alongside `init()`.

## Opting out of auto-discovery

Install only specific integrations, or none:

```python
import introspection_sdk as introspection
from introspection_sdk.integrations.anthropic import AnthropicIntegration

# Only Anthropic, nothing else auto-detected.
introspection.init(auto_discover=False, integrations=[AnthropicIntegration])
```

## Bringing your own TracerProvider

If you already manage an OpenTelemetry `TracerProvider` (e.g. via Logfire or
your own setup), pass it in. `init()` attaches the Introspection exporter to it
instead of creating its own; you keep ownership of its lifecycle.

```python
import introspection_sdk as introspection

introspection.init(tracer_provider=my_provider)
```

## Standalone processors and instrumentors

Each processor works on its own without `init()`. Construct it directly when you
want explicit control. (Preferred path is `init()`; these remain for custom
setups and backward compatibility.)

### Logfire / OpenInference span processor

```python
import logfire
from introspection_sdk import IntrospectionSpanProcessor

logfire.configure(additional_span_processors=[IntrospectionSpanProcessor()])
logfire.instrument_openai()
```

### OpenAI Agents SDK

```python
from agents import set_trace_processors
from introspection_sdk import IntrospectionTracingProcessor

set_trace_processors([IntrospectionTracingProcessor()])
```

Some reasoning models emit items the OpenAI Conversations API rejects;
`IntrospectionConversationsSession` strips them transparently:

```python
from introspection_sdk import IntrospectionConversationsSession

session = IntrospectionConversationsSession(conversation_id="conv_123")
result = await Runner.run(agent, "Hello!", session=session)
```

### Claude Agent SDK

```python
from introspection_sdk import ClaudeTracingProcessor

ClaudeTracingProcessor().configure()  # all ClaudeSDKClient instances traced
```

### Anthropic SDK

```python
from introspection_sdk.anthropic import AnthropicInstrumentor

AnthropicInstrumentor().instrument(tracer_provider=provider)
```

### Gemini (google-genai)

```python
from introspection_sdk.gemini import GeminiInstrumentor

GeminiInstrumentor().instrument(tracer_provider=provider)
```

### LangChain / LangGraph

```python
from introspection_sdk import IntrospectionCallbackHandler

handler = IntrospectionCallbackHandler(service_name="my-app")
response = model.invoke("Hello!", config={"callbacks": [handler]})
```

For LangGraph, pass the app's session id as `thread_id`; the handler maps it to
`gen_ai.conversation.id`:

```python
response = graph.invoke(
    {"messages": [{"role": "user", "content": "Hello!"}]},
    config={"callbacks": [handler], "configurable": {"thread_id": "user-123"}},
)
```

## Sharing one provider across `init()` and a standalone processor

The processors accept a `tracer_provider=` to run in shared-provider mode: they
use the passed provider and treat `shutdown()`/`force_flush()` as no-ops, since
the caller owns its lifecycle. This is exactly how `init()` wires each
integration.

```python
provider = introspection.get_tracer_provider()
processor = IntrospectionTracingProcessor(tracer_provider=provider)
```

## Testing with an in-memory exporter

Pass a `span_exporter` via `AdvancedOptions` to capture spans without network:

```python
from introspection_sdk import AdvancedOptions
from introspection_sdk.testing import TestSpanExporter

exporter = TestSpanExporter()
introspection.init(advanced=AdvancedOptions(span_exporter=exporter))
# ... run code ...
spans = exporter.get_finished_spans()
```
