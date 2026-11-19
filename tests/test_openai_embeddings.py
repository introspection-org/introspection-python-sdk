"""OpenAI embeddings GenAI telemetry tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from introspection_sdk.otel.openai import (
    async_traced_embeddings_create,
    traced_embeddings_create,
)


class _SyncEmbeddings:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self._response


class _AsyncEmbeddings(_SyncEmbeddings):
    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self._response


def _response() -> Any:
    return SimpleNamespace(
        model="text-embedding-3-small",
        usage=SimpleNamespace(prompt_tokens=8, total_tokens=8),
        data=[
            SimpleNamespace(
                index=0,
                embedding=[0.1, 0.2, 0.3, 0.4],
            )
        ],
    )


@pytest.fixture
def capture() -> tuple[Any, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test-openai-embeddings"), exporter


def _assert_embedding_span(exporter: InMemorySpanExporter) -> None:
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    attrs = span.attributes or {}
    assert span.name == "embeddings text-embedding-3-small"
    assert attrs["gen_ai.operation.name"] == "embeddings"
    assert attrs["gen_ai.provider.name"] == "openai"
    assert attrs["gen_ai.request.model"] == "text-embedding-3-small"
    assert attrs["gen_ai.response.model"] == "text-embedding-3-small"
    assert attrs["gen_ai.usage.input_tokens"] == 8
    assert attrs["gen_ai.embeddings.dimension.count"] == 4
    assert "gen_ai.usage.output_tokens" not in attrs
    assert "gen_ai.input.messages" not in attrs
    assert "gen_ai.output.messages" not in attrs
    serialized = repr(dict(attrs))
    assert "private observation text" not in serialized
    assert "0.1, 0.2, 0.3, 0.4" not in serialized


def test_traced_embeddings_create_records_metadata_only(
    capture: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = capture
    embeddings = _SyncEmbeddings(_response())
    client = SimpleNamespace(embeddings=embeddings)

    result = traced_embeddings_create(
        tracer,
        client,
        model="text-embedding-3-small",
        input=["private observation text"],
        dimensions=512,
        encoding_format="float",
    )

    assert result is embeddings._response
    assert embeddings.kwargs is not None
    assert embeddings.kwargs["input"] == ["private observation text"]
    _assert_embedding_span(exporter)


@pytest.mark.asyncio
async def test_async_traced_embeddings_create_records_metadata_only(
    capture: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = capture
    embeddings = _AsyncEmbeddings(_response())
    client = SimpleNamespace(embeddings=embeddings)

    result = await async_traced_embeddings_create(
        tracer,
        client,
        model="text-embedding-3-small",
        input=["private observation text"],
        dimensions=512,
    )

    assert result is embeddings._response
    _assert_embedding_span(exporter)


def test_provider_reported_cost_is_lifted(
    capture: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = capture
    response = _response()
    response.usage.cost = 0.0002
    response.usage.cost_details = {"upstream_inference_cost": 0.0001}
    client = SimpleNamespace(embeddings=_SyncEmbeddings(response))

    traced_embeddings_create(
        tracer, client, model="text-embedding-3-small", input=["x"]
    )

    attrs = exporter.get_finished_spans()[0].attributes or {}
    assert attrs["introspection.llm.cost_usd"] == 0.0002
    assert attrs["introspection.llm.upstream_cost_usd"] == 0.0001


@pytest.mark.asyncio
async def test_a_cancelled_call_reads_as_cancelled_not_failed(
    capture: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = capture

    class _Cancelled:
        async def create(self, **_kwargs: Any) -> Any:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await async_traced_embeddings_create(
            tracer,
            SimpleNamespace(embeddings=_Cancelled()),
            model="m",
            input=["x"],
        )

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.UNSET
    assert (span.attributes or {})[
        "introspection.termination_reason"
    ] == "cancelled"


def test_a_failed_call_is_an_error(
    capture: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = capture

    class _Failing:
        def create(self, **_kwargs: Any) -> Any:
            raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        traced_embeddings_create(
            tracer,
            SimpleNamespace(embeddings=_Failing()),
            model="m",
            input=["x"],
        )

    assert (
        exporter.get_finished_spans()[0].status.status_code is StatusCode.ERROR
    )
