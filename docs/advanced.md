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

## The HTTP client: httpx2, not httpx

(This one is core-SDK, not `otel` — it applies to every install.)

Every REST call goes through [`httpx2`](https://github.com/pydantic/httpx2),
the Pydantic-maintained successor to `httpx`. `httpx` itself is no longer
maintained, and the OpenAI, Anthropic and MCP SDKs have made the same move, so
an application holding all four now shares one connection stack instead of two.

This only concerns you if you hand the SDK an HTTP object of your own. The
`transport=` argument on `IntrospectionClient` / `AsyncIntrospectionClient`
(and on the `auth` helpers) is typed `httpx2.BaseTransport` /
`httpx2.AsyncBaseTransport`, and an `httpx` transport is no longer accepted:

```python
import httpx2

from introspection_sdk import IntrospectionClient

client = IntrospectionClient(token="...", transport=httpx2.HTTPTransport(retries=3))
```

The same applies to anything you build around a response or exception the SDK
re-raises — `httpx2.Response`, `httpx2.HTTPError` — and to tests that pin
requests with `httpx2.MockTransport`. Passing plain values (a float timeout, a
base URL) is unaffected.

One behavioural difference is worth knowing: httpx2 verifies TLS against the
**operating system trust store** rather than a bundled `certifi` copy. On a
normal host or container that is a better default and needs no configuration.
In an image with no CA bundle, or behind a TLS-inspecting proxy with a private
root, point `SSL_CERT_FILE` / `SSL_CERT_DIR` at the bundle, or pass your own
`ssl.SSLContext` as `verify=` on a transport you construct.

If your application also depends on libraries that still `import httpx`, call
`httpx2.alias_httpx()` once at startup — before any other import — to point
them at the same stack. That is an application-level decision, so this SDK
never does it for you.

