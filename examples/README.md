# Introspection SDK examples

## Setup

```bash
cd examples
uv sync
export INTROSPECTION_TOKEN=your-token
```

## Runner execution API

```bash
uv run python -m introspection_examples.api.runtimes
uv run python -m introspection_examples.api.async_runtimes
uv run python -m introspection_examples.api.service_account
```

These examples cover the supported application SDK surface: opening a runner
from a configured runtime, starting and streaming tasks, and using files,
shares, conversations, events, and metrics. Runtime configuration and other
operator workflows remain outside this SDK.

Optional OTLP logs and traces are documented in the repository's
[`docs/otel.md`](../docs/otel.md).
