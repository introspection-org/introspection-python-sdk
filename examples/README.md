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

## Tracing

The SDK ships no framework integrations. Instrument with any library that
emits OTel spans — `IntrospectionSpanProcessor` converts Logfire and
OpenInference spans to GenAI semantic conventions on the way out — or
instrument manually against the OTel APIs.

```bash
uv run -m introspection_examples.otel.logfire_examples.openai_example     # OpenAI client
uv run -m introspection_examples.otel.logfire_examples.anthropic_example  # Anthropic client
```

## Directory Structure

```
examples/introspection_examples/
  api/                 # REST API (IntrospectionClient, Runner, tasks, files)
  otel/                # OpenTelemetry-based instrumentation
    logfire_examples/  # Logfire (OpenAI / Anthropic clients)
```
