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

### Optional Extras

```shell
pip install 'introspection-sdk[openai-agents]'  # OpenAI Agents SDK
pip install 'introspection-sdk[langfuse]'        # Langfuse
pip install 'introspection-sdk[braintrust]'      # Braintrust
pip install 'introspection-sdk[arize]'           # Arize Phoenix + OpenInference
```

## Environment Variables

```shell
export INTROSPECTION_TOKEN="intro_xxx"
export INTROSPECTION_BASE_URL="https://otel.introspection.dev"  # optional
```

## Quickstart

### OpenTelemetry Span Processor

```python
from introspection_sdk import IntrospectionSpanProcessor
import logfire

logfire.configure(
    additional_span_processors=[IntrospectionSpanProcessor()],
)

logfire.instrument_openai()
```

### OpenAI Agents SDK

```python
from agents import Agent, Runner, set_trace_processors, tool
from introspection_sdk import IntrospectionTracingProcessor

set_trace_processors([IntrospectionTracingProcessor()])

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny, 72F in {city}"

agent = Agent(name="Weather Bot", tools=[get_weather])
result = await Runner.run(agent, "What's the weather in Tokyo?")
```

#### Reasoning Model Support

Some models produce reasoning items that the OpenAI Conversations API rejects. `IntrospectionConversationsSession` strips those items transparently:

```python
from introspection_sdk import IntrospectionConversationsSession

session = IntrospectionConversationsSession(conversation_id="conv_123")
result = await Runner.run(agent, "Hello!", session=session)
```

### Claude Agent SDK

```python
from introspection_sdk import ClaudeTracingProcessor

processor = ClaudeTracingProcessor()
processor.configure()

# All ClaudeSDKClient instances are now automatically traced
```

### LangChain / LangGraph

```python
from introspection_sdk import IntrospectionCallbackHandler

handler = IntrospectionCallbackHandler(service_name="my-app")
response = model.invoke("Hello!", config={"callbacks": [handler]})
```

### Anthropic SDK

```python
from introspection_sdk.anthropic import AnthropicInstrumentor

instrumentor = AnthropicInstrumentor()
instrumentor.instrument(tracer_provider=provider)

# All client.messages.create calls are traced, including thinking blocks
```

### OpenInference (Arize, Langfuse, Braintrust)

```python
from opentelemetry.sdk.trace import TracerProvider
from openinference.instrumentation.openai import OpenAIInstrumentor
from introspection_sdk import IntrospectionSpanProcessor

provider = TracerProvider()
provider.add_span_processor(IntrospectionSpanProcessor())
OpenAIInstrumentor().instrument(tracer_provider=provider)
```

> See [examples/](./examples/) for complete integration patterns including dual-export with Arize, Langfuse, Braintrust, and LangSmith.

## Client API

```python
from introspection_sdk import IntrospectionClient

client = IntrospectionClient()

with client.set_user_id("user_123"):
    with client.set_conversation("conv_456", previous_response_id="msg_123"):
        client.feedback("thumbs_up", comments="Great response!")

client.shutdown()
```

### Methods

| Method | Description |
| ------ | ----------- |
| `feedback(type, **kwargs)` | Track feedback on AI responses |
| `identify(user_id, traits=)` | Associate a user with traits (context manager) |
| `track(event, properties=)` | Track any user action |
| `flush(timeout_ms=30000)` | Flush pending events |
| `shutdown()` | Shutdown and flush |

### Context Managers

| Method | Description |
| ------ | ----------- |
| `set_user_id(id)` | Set user context |
| `set_conversation(id?, response_id?)` | Set conversation context |
| `set_agent(name, id?)` | Set agent context |
| `set_anonymous_id(id)` | Set anonymous ID |
| `set_baggage(**values)` | Set arbitrary baggage values |

## Documentation

Full documentation is available at [docs.introspection.dev](https://docs.introspection.dev).
