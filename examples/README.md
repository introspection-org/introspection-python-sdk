# Introspection SDK Examples

## Setup

```bash
cd examples
uv sync
export INTROSPECTION_TOKEN=your-token
```

## REST API

```bash
uv run python -m introspection_examples.api.runtimes                 # Runner: tasks + files end-to-end (sync)
uv run python -m introspection_examples.api.async_runtimes           # AsyncRunner: same flow on asyncio
```

## Tracing

There are no tracing examples here. The Python SDK ships no framework
integrations: attach `IntrospectionSpanProcessor` to your provider and
instrument with any OTel-emitting library, or instrument manually. See
[`../docs/otel.md`](../docs/otel.md).

## Directory Structure

```
examples/introspection_examples/
  api/                 # REST API (IntrospectionClient, Runner, tasks, files)
```
