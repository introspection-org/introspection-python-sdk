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

## Experimental framework examples

### Claude Agent SDK

```bash
uv run -m introspection_examples.otel.claude_agent.claude_braintrust     # + Braintrust
uv run -m introspection_examples.otel.claude_agent.claude_arize          # + Arize
uv run -m introspection_examples.otel.claude_agent.claude_langsmith      # + LangSmith
uv run -m introspection_examples.otel.claude_agent.claude_langfuse       # + Langfuse
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
    claude_agent/      # Claude Agent SDK (first-party integration)
    logfire_examples/  # Logfire (OpenAI / Anthropic clients)
    openinference/     # OpenInference (OpenAI + Anthropic with dual export)
```
