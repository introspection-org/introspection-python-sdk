# Introspection SDK Examples

## Setup

```bash
cd examples
uv sync --extra all
export INTROSPECTION_TOKEN=your-token
```

## First-Party Integrations

### OpenAI Agents SDK

```bash
uv run -m introspection_examples.openai_agents.example              # Basic tracing
uv run -m introspection_examples.openai_agents.responses_api_features  # Responses API (web search, reasoning, MCP)
uv run -m introspection_examples.openai_agents.agents_braintrust    # + Braintrust
uv run -m introspection_examples.openai_agents.agents_arize         # + Arize
uv run -m introspection_examples.openai_agents.agents_langsmith     # + LangSmith
uv run -m introspection_examples.openai_agents.agents_langfuse      # + Langfuse
```

### Anthropic SDK (native)

Uses `AnthropicInstrumentor` to capture the full Anthropic response including extended thinking blocks with signatures:

```bash
uv run -m introspection_examples.anthropic_sdk.anthropic_native     # Thinking + tool calling
```

### Claude Agent SDK

```bash
uv run -m introspection_examples.claude_agent.claude_braintrust     # + Braintrust
uv run -m introspection_examples.claude_agent.claude_arize          # + Arize
uv run -m introspection_examples.claude_agent.claude_langsmith      # + LangSmith
uv run -m introspection_examples.claude_agent.claude_langfuse       # + Langfuse
```

### LangChain / LangGraph

```bash
uv run -m introspection_examples.langchain_langgraph.handler        # IntrospectionCallbackHandler
```

### Logfire

```bash
uv run -m introspection_examples.logfire_examples.openai_example             # OpenAI client
uv run -m introspection_examples.logfire_examples.anthropic_example          # Anthropic client
uv run -m introspection_examples.logfire_examples.openai_langfuse_example    # + Langfuse dual export
uv run -m introspection_examples.logfire_examples.openai_braintrust_example  # + Braintrust dual export
```

## OpenInference

### OpenAI

Multi-turn tool calling with dual export to observability platforms:

```bash
uv run -m introspection_examples.openinference.openai_arize          # + Arize/Phoenix
uv run -m introspection_examples.openinference.openai_braintrust     # + Braintrust
uv run -m introspection_examples.openinference.openai_langfuse       # + Langfuse
```

### Anthropic

Multi-turn tool calling with dual export to observability platforms:

```bash
uv run -m introspection_examples.openinference.anthropic_arize       # + Arize/Phoenix
uv run -m introspection_examples.openinference.anthropic_braintrust  # + Braintrust
uv run -m introspection_examples.openinference.anthropic_langfuse    # + Langfuse
```

## Directory Structure

```
examples/introspection_examples/
  openai_agents/       # OpenAI Agents SDK (first-party integration)
  anthropic_sdk/       # Anthropic SDK (native AnthropicInstrumentor)
  claude_agent/        # Claude Agent SDK (first-party integration)
  langchain_langgraph/ # LangChain / LangGraph
  logfire_examples/    # Logfire (OpenAI / Anthropic clients)
  openinference/       # OpenInference (OpenAI + Anthropic with dual export)
```
