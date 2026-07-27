"""Privacy-preserving OpenAI embeddings instrumentation.

The helpers in this module deliberately capture only GenAI request/response
metadata required for usage reporting. Embedding inputs and vectors are never
attached to spans.
"""

from __future__ import annotations

__all__ = [
    "async_traced_embeddings_create",
    "traced_embeddings_create",
]

from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, StatusCode

from introspection_sdk.otel._termination import (
    CANCELLATION_EXCEPTIONS,
    mark_span_cancelled,
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping or SDK response object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _start_embeddings_span(
    tracer: trace.Tracer,
    *,
    model: str,
    provider_name: str,
    dimensions: int | None,
    encoding_format: str | None,
) -> tuple[Span, object]:
    attributes: dict[str, Any] = {
        "gen_ai.system": provider_name,
        "gen_ai.provider.name": provider_name,
        "gen_ai.operation.name": "embeddings",
        "gen_ai.request.model": model,
        "openinference.span.kind": "EMBEDDING",
    }
    if dimensions is not None:
        attributes["gen_ai.embeddings.dimension.count"] = dimensions
    if encoding_format:
        attributes["gen_ai.request.encoding_formats"] = [encoding_format]

    span = tracer.start_span(
        f"embeddings {model}",
        kind=SpanKind.CLIENT,
        attributes=attributes,
    )
    token = otel_context.attach(trace.set_span_in_context(span))
    return span, token


def _set_embeddings_response_attrs(span: Span, response: Any) -> None:
    response_model = _get(response, "model")
    if response_model:
        span.set_attribute("gen_ai.response.model", response_model)

    usage = _get(response, "usage")
    prompt_tokens = _get(usage, "prompt_tokens") if usage is not None else None
    if prompt_tokens is not None:
        # Embeddings produce no output tokens. OpenAI's total_tokens is the
        # same input total and must not be reported as output usage.
        span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)

    data = _get(response, "data") or []
    if data:
        embedding = _get(data[0], "embedding")
        if isinstance(embedding, (list, tuple)):
            span.set_attribute(
                "gen_ai.embeddings.dimension.count", len(embedding)
            )

    span.set_status(StatusCode.OK)


def traced_embeddings_create(
    tracer: trace.Tracer,
    client: Any,
    *,
    provider_name: str = "openai",
    **kwargs: Any,
) -> Any:
    """Call ``client.embeddings.create`` and emit a metadata-only span."""
    span, token = _start_embeddings_span(
        tracer,
        model=kwargs.get("model", "unknown"),
        provider_name=provider_name,
        dimensions=kwargs.get("dimensions"),
        encoding_format=kwargs.get("encoding_format"),
    )
    try:
        response = client.embeddings.create(**kwargs)
        _set_embeddings_response_attrs(span, response)
        return response
    except CANCELLATION_EXCEPTIONS:
        mark_span_cancelled(span)
        raise
    except Exception as exc:
        span.set_status(StatusCode.ERROR, str(exc))
        raise
    finally:
        otel_context.detach(token)  # type: ignore[arg-type]
        span.end()


async def async_traced_embeddings_create(
    tracer: trace.Tracer,
    client: Any,
    *,
    provider_name: str = "openai",
    **kwargs: Any,
) -> Any:
    """Async equivalent of :func:`traced_embeddings_create`."""
    span, token = _start_embeddings_span(
        tracer,
        model=kwargs.get("model", "unknown"),
        provider_name=provider_name,
        dimensions=kwargs.get("dimensions"),
        encoding_format=kwargs.get("encoding_format"),
    )
    try:
        response = await client.embeddings.create(**kwargs)
        _set_embeddings_response_attrs(span, response)
        return response
    except CANCELLATION_EXCEPTIONS:
        mark_span_cancelled(span)
        raise
    except Exception as exc:
        span.set_status(StatusCode.ERROR, str(exc))
        raise
    finally:
        otel_context.detach(token)  # type: ignore[arg-type]
        span.end()
