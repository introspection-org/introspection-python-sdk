# Advanced OTLP setup

The runner execution API does not require OpenTelemetry. Install the optional
extra only when the application also needs to emit analytics logs or export
traces:

```shell
pip install 'introspection-sdk[otel]'
```

## Bringing your own TracerProvider

Attach the Introspection processor to an OpenTelemetry provider that your
application already owns:

```python
from opentelemetry.sdk.trace import TracerProvider

from introspection_sdk import IntrospectionSpanProcessor

provider = TracerProvider()
provider.add_span_processor(IntrospectionSpanProcessor())
```

The processor forwards standard OpenTelemetry spans to the configured OTLP
endpoint. Provider lifecycle remains with the application.

## Custom exporter and headers

Use `AdvancedOptions` for a custom exporter, additional headers, or batching
configuration:

```python
from introspection_sdk import AdvancedOptions, IntrospectionSpanProcessor

options = AdvancedOptions(
    additional_headers={"X-Tenant": "example"},
    flush_interval_ms=1000,
)
processor = IntrospectionSpanProcessor(advanced=options)
```

See [`otel.md`](otel.md) for the supported OTLP logs and traces surface.
