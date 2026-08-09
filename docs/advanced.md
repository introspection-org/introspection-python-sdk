# Advanced setup

Escape hatches for callers who need more control than `init()` gives them.

## Bringing your own TracerProvider

If you already manage an OpenTelemetry `TracerProvider`, pass it in. `init()` attaches the Introspection exporter to it
instead of creating its own; you keep ownership of its lifecycle.

```python
import introspection_sdk as introspection

introspection.init(tracer_provider=my_provider)
```

## Standalone processors and instrumentors

Each processor works on its own without `init()`. Construct it directly when you
want explicit control. (Preferred path is `init()`; these remain for custom
setups and backward compatibility.)

### Span processor

Attach it to whatever provider you already have; every `gen_ai.*` span that
reaches the provider is exported to Introspection.

```python
from opentelemetry.sdk.trace import TracerProvider
from introspection_sdk import IntrospectionSpanProcessor

provider = TracerProvider()
provider.add_span_processor(IntrospectionSpanProcessor())
```

## Sharing one provider across `init()` and a standalone processor

The processors accept a `tracer_provider=` to run in shared-provider mode: they
use the passed provider and treat `shutdown()`/`force_flush()` as no-ops, since
the caller owns its lifecycle. This is exactly how `init()` wires each
integration.

```python
provider = introspection.get_tracer_provider()
processor = IntrospectionSpanProcessor(tracer_provider=provider)
```

## Testing with an in-memory exporter

Pass a `span_exporter` via `AdvancedOptions` to capture spans without network:

```python
from introspection_sdk import AdvancedOptions
from introspection_sdk.testing import TestSpanExporter

exporter = TestSpanExporter()
introspection.init(advanced=AdvancedOptions(span_exporter=exporter))
# ... run code ...
spans = exporter.get_finished_spans()
```
