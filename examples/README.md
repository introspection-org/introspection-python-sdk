# Introspection SDK Examples

## Setup

```bash
cd examples
uv sync --extra all
export INTROSPECTION_TOKEN=your-token
```

## REST API

```bash
uv run python -m introspection_examples.api.runtimes                 # Runner: tasks + files end-to-end (sync)
uv run python -m introspection_examples.api.async_runtimes           # AsyncRunner: same flow on asyncio
```

## One-liner: `introspection.init()`

A single `introspection.init()` auto-detects the installed LLM frameworks and
wires them in. The dual-export examples below also send traces to a third-party
backend *and* Introspection at once — by putting the backend's exporter on the
global `TracerProvider` before calling `init()`, which then attaches
Introspection's pipeline to the same provider:

```bash
uv run -m introspection_examples.otel.anthropic_sdk.anthropic_langfuse_init    # Anthropic + Langfuse
uv run -m introspection_examples.otel.anthropic_sdk.anthropic_langsmith_init   # Anthropic + LangSmith
uv run -m introspection_examples.otel.gemini_sdk.gemini_arize_init             # Gemini + Arize
uv run -m introspection_examples.otel.openai_agents.agents_braintrust_init     # OpenAI Agents + Braintrust
uv run -m introspection_examples.otel.gemini_sdk.gemini_init                   # Gemini only (no dual export)
```

## First-Party Integrations

### OpenAI Agents SDK

```bash
uv run -m introspection_examples.otel.openai_agents.example              # Basic tracing
uv run -m introspection_examples.otel.openai_agents.responses_api_features  # Responses API (web search, reasoning, MCP)
uv run -m introspection_examples.otel.openai_agents.agents_braintrust    # + Braintrust
uv run -m introspection_examples.otel.openai_agents.agents_arize         # + Arize
uv run -m introspection_examples.otel.openai_agents.agents_langsmith     # + LangSmith
uv run -m introspection_examples.otel.openai_agents.agents_langfuse      # + Langfuse
```

### Anthropic SDK (native)

Uses `AnthropicInstrumentor` to capture the full Anthropic response including extended thinking blocks with signatures:

```bash
uv run -m introspection_examples.otel.anthropic_sdk.anthropic_native     # Thinking + tool calling
```

### Gemini SDK (native)

Uses `GeminiInstrumentor` to capture the full Gemini response including thought signatures — encrypted reasoning-state tokens that Gemini 3.x attaches to text and function-call parts and must be replayed on subsequent turns:

```bash
uv run -m introspection_examples.otel.gemini_sdk.gemini_native           # Thought signatures + tool calling
```

### Claude Agent SDK

```bash
uv run -m introspection_examples.otel.claude_agent.claude_braintrust     # + Braintrust
uv run -m introspection_examples.otel.claude_agent.claude_arize          # + Arize
uv run -m introspection_examples.otel.claude_agent.claude_langsmith      # + LangSmith
uv run -m introspection_examples.otel.claude_agent.claude_langfuse       # + Langfuse
```

### LangChain / LangGraph

```bash
uv run -m introspection_examples.otel.langchain_langgraph.handler        # IntrospectionCallbackHandler
```

For LangGraph, pass the app's session id in `configurable.thread_id`. The
callback handler maps that internal LangGraph thread id to
`gen_ai.conversation.id`, so each graph thread appears as a distinct
Introspection conversation.

```python
thread_id = "user-session-123"
await graph.ainvoke(
    input,
    config={"callbacks": [handler], "configurable": {"thread_id": thread_id}},
)
```

### Logfire

```bash
uv run -m introspection_examples.otel.logfire_examples.openai_example             # OpenAI client
uv run -m introspection_examples.otel.logfire_examples.anthropic_example          # Anthropic client
uv run -m introspection_examples.otel.logfire_examples.openai_langfuse_example    # + Langfuse dual export
uv run -m introspection_examples.otel.logfire_examples.openai_braintrust_example  # + Braintrust dual export
```

## OpenInference

### OpenAI

Multi-turn tool calling with dual export to observability platforms:

```bash
uv run -m introspection_examples.otel.openinference.openai_arize          # + Arize/Phoenix
uv run -m introspection_examples.otel.openinference.openai_braintrust     # + Braintrust
uv run -m introspection_examples.otel.openinference.openai_langfuse       # + Langfuse
```

### Anthropic

Multi-turn tool calling with dual export to observability platforms:

```bash
uv run -m introspection_examples.otel.openinference.anthropic_arize       # + Arize/Phoenix
uv run -m introspection_examples.otel.openinference.anthropic_braintrust  # + Braintrust
uv run -m introspection_examples.otel.openinference.anthropic_langfuse    # + Langfuse
```

## Directory Structure

```
examples/introspection_examples/
  api/                 # REST API (IntrospectionClient, Runner, tasks, files)
  otel/                # OpenTelemetry-based integrations
    openai_agents/     # OpenAI Agents SDK (first-party integration)
    anthropic_sdk/     # Anthropic SDK (native AnthropicInstrumentor)
    gemini_sdk/        # Google Gemini SDK (native GeminiInstrumentor)
    claude_agent/      # Claude Agent SDK (first-party integration)
    langchain_langgraph/ # LangChain / LangGraph
    logfire_examples/  # Logfire (OpenAI / Anthropic clients)
    openinference/     # OpenInference (OpenAI + Anthropic with dual export)
```
