"""OpenAI embeddings GenAI telemetry tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from introspection_sdk.otel.openai import (
    async_traced_embeddings_create,
    traced_embeddings_create,
)


def test_embedding_helpers_are_public_without_openai_agents() -> None:
    from introspection_sdk import (
        async_traced_embeddings_create as public_async,
    )
    from introspection_sdk import traced_embeddings_create as public_sync

    assert public_async is async_traced_embeddings_create
    assert public_sync is traced_embeddings_create


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
