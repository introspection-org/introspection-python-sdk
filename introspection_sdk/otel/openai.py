"""Privacy-preserving OpenAI embeddings instrumentation.

The helpers capture only the GenAI request and response metadata usage
reporting needs: the model, input tokens, the vector width and any
provider-reported cost. Embedding inputs and vectors never reach a span.

Conversation and agent identity come from baggage, as for every span the
:class:`IntrospectionSpanProcessor` exports, so wrap a call in
``with_conversation(...)`` and ``with_agent(...)`` to attribute it.
"""

from __future__ import annotations

__all__ = [
    "async_traced_embeddings_create",
    "traced_embeddings_create",
]

import asyncio
from contextvars import Token
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, SpanKind, StatusCode

from introspection_sdk.otel.types import Attr

# A caller stopping the call is not a failure: the span keeps an Unset status
# and says it was cancelled, as the JS SDK's spans do.
_CANCELLATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    GeneratorExit,
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping or SDK response object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _start_span(
    tracer: trace.Tracer, provider_name: str, kwargs: dict[str, Any]
) -> tuple[Span, Token[Context]]:
    model = kwargs.get("model", "unknown")
    attributes: dict[str, Any] = {
        "gen_ai.provider.name": provider_name,
        "gen_ai.operation.name": "embeddings",
        "gen_ai.request.model": model,
    }
    if kwargs.get("dimensions") is not None:
        attributes["gen_ai.embeddings.dimension.count"] = kwargs["dimensions"]
    if kwargs.get("encoding_format"):
        attributes["gen_ai.request.encoding_formats"] = [
            kwargs["encoding_format"]
        ]
    span = tracer.start_span(
        f"embeddings {model}", kind=SpanKind.CLIENT, attributes=attributes
    )
    return span, otel_context.attach(trace.set_span_in_context(span))


def _record_response(span: Span, response: Any) -> None:
    response_model = _get(response, "model")
    if response_model:
        span.set_attribute("gen_ai.response.model", response_model)
    usage = _get(response, "usage")
    if usage is not None:
        prompt_tokens = _get(usage, "prompt_tokens")
        if prompt_tokens is not None:
            # Embeddings produce no output tokens; total_tokens repeats the
            # input total and must not be reported as output.
            span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
        cost = _cost(_get(usage, "cost"))
        if cost is not None:
            span.set_attribute(Attr.LLM_COST_USD, cost)
        upstream = _cost(
            _get(_get(usage, "cost_details"), "upstream_inference_cost")
        )
        if upstream is not None:
            span.set_attribute(Attr.LLM_UPSTREAM_COST_USD, upstream)
    data = _get(response, "data") or []
    if data:
        embedding = _get(data[0], "embedding")
        if isinstance(embedding, (list, tuple)):
            span.set_attribute(
                "gen_ai.embeddings.dimension.count", len(embedding)
            )
    span.set_status(StatusCode.OK)


def _mark_cancelled(span: Span) -> None:
    span.set_attribute("gen_ai.response.finish_reasons", ["aborted"])
    span.set_attribute(Attr.TERMINATION_REASON, "cancelled")


def traced_embeddings_create(
    tracer: trace.Tracer,
    client: Any,
    *,
    provider_name: str = "openai",
    **kwargs: Any,
) -> Any:
    """Call ``client.embeddings.create`` and emit a metadata-only span."""
    span, token = _start_span(tracer, provider_name, kwargs)
    try:
        response = client.embeddings.create(**kwargs)
        _record_response(span, response)
        return response
    except _CANCELLATION_EXCEPTIONS:
        _mark_cancelled(span)
        raise
    except Exception as exc:
        span.set_status(StatusCode.ERROR, str(exc))
        raise
    finally:
        otel_context.detach(token)
        span.end()


async def async_traced_embeddings_create(
    tracer: trace.Tracer,
    client: Any,
    *,
    provider_name: str = "openai",
    **kwargs: Any,
) -> Any:
    """Async equivalent of :func:`traced_embeddings_create`."""
    span, token = _start_span(tracer, provider_name, kwargs)
    try:
        response = await client.embeddings.create(**kwargs)
        _record_response(span, response)
        return response
    except _CANCELLATION_EXCEPTIONS:
        _mark_cancelled(span)
        raise
    except Exception as exc:
        span.set_status(StatusCode.ERROR, str(exc))
        raise
    finally:
        otel_context.detach(token)
        span.end()
