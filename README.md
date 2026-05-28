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

## Environment Variables

```shell
export INTROSPECTION_TOKEN="intro_xxx"
export INTROSPECTION_BASE_URL="https://otel.introspection.dev"  # optional
```

## Quickstart

One line. `introspection.init()` detects every supported LLM framework you have
installed and wires them all into a single trace pipeline:

```python
import introspection_sdk as introspection

introspection.init()  # token from INTROSPECTION_TOKEN

# ...use Anthropic, Gemini, OpenAI Agents, Claude Agent, Logfire as usual —
# their calls are now traced automatically.
```

### Supported frameworks

| Framework | Auto-detected by `init()` |
| --------- | ------------------------- |
| Anthropic SDK | ✅ |
| Google Gemini (`google-genai`) | ✅ |
| OpenAI Agents SDK | ✅ |
| Claude Agent SDK | ✅ |
| Logfire / OpenInference | ✅ (configure Logfire before `init()`) |
| LangChain / LangGraph | ✅ (attach `get_handler()` — see below) |

LangChain callbacks are per-invoke, so `init()` prepares the handler and you
attach it:

```python
import introspection_sdk as introspection
from introspection_sdk.integrations.langchain import get_handler

introspection.init()
response = model.invoke("Hello!", config={"callbacks": [get_handler()]})
```

### Identity, feedback, and conversations

```python
import introspection_sdk as introspection

introspection.init()

with introspection.identify("user_123", traits={"plan": "pro"}):
    with introspection.conversation("conv_456"):
        # LLM calls here share one conversation id automatically
        introspection.feedback("thumbs_up", comments="Great response!")
        introspection.track("checkout_completed", {"amount": 42})
```

`introspection.conversation()` scopes a conversation id across every span and
event produced inside it; omit the id to auto-generate one.

## Manual / advanced setup

`init()` is the recommended entry point, but the individual processors and
instrumentors remain fully supported for custom wiring (sharing a
`TracerProvider`, dual-export, testing). See
[`docs/advanced.md`](docs/advanced.md) for opting out of auto-discovery,
passing your own provider, standalone processor construction, and testing with
an in-memory exporter.

> See [examples/](./examples/) for complete integration patterns including
> dual-export with Arize, Langfuse, Braintrust, and LangSmith.

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

## Contributing

See [`AGENTS.md`](AGENTS.md) for contribution rules, including the
recordings-over-mocks policy and the coverage ratchet enforced in CI.
The phased plan for closing current test gaps lives in
[`docs/test-quality-audit-plan.md`](docs/test-quality-audit-plan.md).
