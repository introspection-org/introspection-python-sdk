# Advanced setup

Escape hatches for callers who need more control than `init()` gives them.

`init()` lives on the `otel` submodule, not the package root — the root only
lazily re-exports `AdvancedOptions`, `Attr`, `Baggage`, `EventName`,
`FeedbackProperties`, `IntrospectionLogs`, and `IntrospectionSpanProcessor`.

```python
from introspection_sdk import otel as introspection
```

All of this requires the `otel` extra: `pip install introspection-sdk[otel]`.

## Bringing your own TracerProvider

If you already manage an OpenTelemetry `TracerProvider`, pass it in. `init()`
attaches the Introspection exporter to it instead of creating its own; you keep
ownership of its lifecycle.

```python
introspection.init(tracer_provider=my_provider)
```

## Standalone span processor

`IntrospectionSpanProcessor` works on its own without `init()`. Attach it to
whatever provider you already have; every `gen_ai.*` span that reaches the
provider is exported to Introspection, and everything else is dropped (see
[otel.md](otel.md) for the exact gate).

```python
from opentelemetry.sdk.trace import TracerProvider
from introspection_sdk import IntrospectionSpanProcessor

provider = TracerProvider()
provider.add_span_processor(IntrospectionSpanProcessor(token="intro_..."))
```

The constructor takes `token`, `service_name`, and `advanced` only. It owns the
exporter it builds, so `shutdown()` and `force_flush()` on your provider reach
it normally.

Note that `init()` also starts the `IntrospectionLogs` stream (the `track` /
`feedback` / `identify` surface) and registers an `atexit` flush; constructing
the processor yourself does not. If you want both, either call `init()` or
construct `IntrospectionLogs` alongside the processor.

## Testing with in-memory exporters

Pass exporters via `AdvancedOptions` to capture telemetry without a network.
Set **both**: `init()` always builds a logs stream, so leaving `log_exporter`
unset points it at the real OTLP endpoint.

```python
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from introspection_sdk import AdvancedOptions
from introspection_sdk.testing import TestSpanExporter

spans = TestSpanExporter()
introspection.init(
    token="test",
    advanced=AdvancedOptions(
        span_exporter=spans,
        log_exporter=InMemoryLogRecordExporter(),
    ),
)
# ... run code ...
finished = spans.get_finished_spans()
```
