"""Tests for IntrospectionSpanProcessor."""

import logging
import os
import threading
import time

import pytest
from dirty_equals import IsStr
from inline_snapshot import snapshot
from opentelemetry import baggage, context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanContext, TraceFlags

from introspection_sdk import AdvancedOptions, IntrospectionSpanProcessor
from introspection_sdk.otel.processors import (
    span_processor as span_processor_module,
)
from introspection_sdk.utils import logger as sdk_logger

from .test_utils import IncrementalIdGenerator, spans_to_dict

# Matches auto-generated conversation IDs like "intro_conv_<32 hex chars>"
_CONV_ID = IsStr(regex=r"^intro_conv_[0-9a-f]{32}$")

#: The processor only exports spans carrying gen_ai data, so every span in
#: these tests sets the minimum marker.
_MODEL = "claude-haiku-4-5"


class TestIntrospectionSpanProcessor:
    """Test suite for IntrospectionSpanProcessor."""

    def test_span_processor_creation_with_token(self):
        """Test basic creation with token."""
        processor = IntrospectionSpanProcessor(token="test-token")
        assert processor is not None
        assert processor.force_flush(1000) is True

    def test_span_processor_creation_with_advanced_options(self):
        """Test creation with advanced options."""
        custom_headers = {"X-Custom-Header": "custom-value"}

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                base_url="http://localhost:5418/v1/traces",
                additional_headers=custom_headers,
            ),
        )

        assert processor is not None
        assert processor.force_flush(1000) is True

    def test_span_processor_applies_explicit_batch_options(self):
        """Callers can override each OpenTelemetry batch setting."""
        processor = IntrospectionSpanProcessor(
            advanced=AdvancedOptions(
                span_exporter=InMemorySpanExporter(),
                max_queue_size=64,
                max_batch_size=8,
                flush_interval_ms=123,
                export_timeout_ms=456,
            ),
        )

        assert isinstance(processor._span_processor, BatchSpanProcessor)
        batch = processor._span_processor._batch_processor
        assert batch._max_queue_size == 64
        assert batch._max_export_batch_size == 8
        assert batch._schedule_delay_millis == 123
        assert batch._export_timeout_millis == 456
        processor.shutdown()

    def test_span_processor_uses_otel_batch_default_when_unspecified(self):
        processor = IntrospectionSpanProcessor(
            advanced=AdvancedOptions(span_exporter=InMemorySpanExporter()),
        )

        assert isinstance(processor._span_processor, BatchSpanProcessor)
        batch = processor._span_processor._batch_processor
        assert batch._max_queue_size == 2048
        assert batch._max_export_batch_size == 512
        assert batch._schedule_delay_millis == 5000
        assert batch._export_timeout_millis == 30000
        processor.shutdown()

    def test_span_processor_with_in_memory_exporter(self):
        """Test processor with in-memory exporter to validate spans."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
            ),
        )

        # Create a tracer provider with our processor
        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("test-tracer")

        # Create and end a span
        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("test.key", "test.value")
            span.set_attribute("test.number", 42)
            span.set_attribute("gen_ai.request.model", _MODEL)

        # Force flush to ensure spans are exported
        processor.force_flush(1000)

        # Convert to dict and compare with snapshot
        # Normalize timestamps for deterministic snapshots
        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-span",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "test.key": "test.value",
                        "test.number": 42,
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        provider.shutdown()

    def test_span_processor_preserves_span_attributes(self):
        """Attributes on a gen_ai span survive processing untouched."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
            ),
        )

        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("test-tracer")

        # Create a span with multiple attributes
        with tracer.start_as_current_span("test-span-with-attributes") as span:
            span.set_attribute("service.name", "test-service")
            span.set_attribute("gen_ai.request.model", _MODEL)
            span.set_attribute("gen_ai.usage.input_tokens", 200)
            span.set_status(trace.Status(trace.StatusCode.OK))

        processor.force_flush(1000)

        # Convert to dict and compare with snapshot
        # Normalize timestamps for deterministic snapshots
        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-span-with-attributes",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "service.name": "test-service",
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.usage.input_tokens": 200,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        provider.shutdown()

    def test_infrastructure_spans_are_not_exported(self):
        """A span with no gen_ai data never reaches the exporter.

        The processor is attached to the global provider, so every HTTP,
        routing, and database span in the process passes through it. Exporting
        those would both ship unrelated traffic and mint a synthetic
        conversation id for a span that has no conversation.
        """
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(span_exporter=exporter),
        )
        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("test-tracer")

        with tracer.start_as_current_span("GET /health") as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("http.response.status_code", 200)

        processor.force_flush(1000)
        assert exporter.get_finished_spans() == ()

        provider.shutdown()

    def test_span_processor_with_custom_exporter(self):
        """Test processor accepts custom exporter via AdvancedOptions."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(span_exporter=exporter),
        )

        # Verify processor was created successfully with custom exporter
        assert processor.force_flush(1000) is True

    def test_span_processor_shutdown(self):
        """Test processor shutdown."""
        processor = IntrospectionSpanProcessor(token="test-token")
        processor.shutdown()
        # Shutdown should complete without error
        assert True

    def test_span_processor_requires_token(self):
        """Test that token is required when not using custom exporter."""
        # Clear any env var that might be set
        old_token = os.environ.pop("INTROSPECTION_TOKEN", None)

        try:
            with pytest.raises(ValueError, match="INTROSPECTION_TOKEN"):
                IntrospectionSpanProcessor()
        finally:
            # Restore the env var if it was set
            if old_token:
                os.environ["INTROSPECTION_TOKEN"] = old_token

    def test_span_processor_uses_env_token(self):
        """Test processor uses INTROSPECTION_TOKEN env var."""
        # Save any existing token
        old_token = os.environ.get("INTROSPECTION_TOKEN")

        try:
            os.environ["INTROSPECTION_TOKEN"] = "env-token"

            processor = IntrospectionSpanProcessor()
            assert processor is not None
        finally:
            # Restore the original token or remove if it didn't exist
            if old_token:
                os.environ["INTROSPECTION_TOKEN"] = old_token
            else:
                os.environ.pop("INTROSPECTION_TOKEN", None)

    def test_span_processor_processes_multiple_spans(self):
        """Test processor handles multiple spans correctly."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
            ),
        )

        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("test-tracer")

        # Create multiple spans
        with tracer.start_as_current_span("span-1") as span:
            span.set_attribute("gen_ai.request.model", _MODEL)

        with tracer.start_as_current_span("span-2") as span:
            span.set_attribute("span.id", 2)
            span.set_attribute("gen_ai.request.model", _MODEL)

        with tracer.start_as_current_span("span-3") as span:
            span.set_attribute("span.id", 3)
            span.set_attribute("gen_ai.request.model", _MODEL)

        processor.force_flush(1000)

        # Convert to dict and compare with snapshot
        # Normalize timestamps for deterministic snapshots
        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "span-1",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "span-2",
                    "context": {
                        "trace_id": 2,
                        "span_id": 2,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 2000000000,
                    "end_time": 3000000000,
                    "attributes": {
                        "span.id": 2,
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "span-3",
                    "context": {
                        "trace_id": 3,
                        "span_id": 3,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 3000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "span.id": 3,
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        provider.shutdown()

    def test_span_processor_with_nested_spans(self):
        """Test processor handles nested spans correctly."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
            ),
        )

        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("test-tracer")

        # Create nested spans
        with tracer.start_as_current_span("parent-span") as parent:
            parent.set_attribute("level", "parent")
            parent.set_attribute("gen_ai.request.model", _MODEL)
            with tracer.start_as_current_span("child-span") as child:
                child.set_attribute("level", "child")
                child.set_attribute("gen_ai.request.model", _MODEL)
                with tracer.start_as_current_span(
                    "grandchild-span"
                ) as grandchild:
                    grandchild.set_attribute("level", "grandchild")
                    grandchild.set_attribute("gen_ai.request.model", _MODEL)

        processor.force_flush(1000)

        # Convert to dict and compare with snapshot
        # Normalize timestamps for deterministic snapshots
        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "grandchild-span",
                    "context": {
                        "trace_id": 1,
                        "span_id": 3,
                        "is_remote": False,
                    },
                    "parent": {
                        "trace_id": 1,
                        "span_id": 2,
                        "is_remote": False,
                    },
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "level": "grandchild",
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "child-span",
                    "context": {
                        "trace_id": 1,
                        "span_id": 2,
                        "is_remote": False,
                    },
                    "parent": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "start_time": 2000000000,
                    "end_time": 3000000000,
                    "attributes": {
                        "level": "child",
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "parent-span",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 3000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "level": "parent",
                        "gen_ai.request.model": _MODEL,
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        provider.shutdown()

    def test_exported_span_preserves_parent(self):
        """The exported copy must not drop parent span context."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
            ),
        )

        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("manual.instrumentation.test")

        # The processor forwards an enriched *copy* of each span, so the
        # parent/trace linkage has to survive the copy.
        with tracer.start_as_current_span("agent") as parent:
            parent.set_attribute("gen_ai.operation.name", "invoke_agent")
            with tracer.start_as_current_span("chat") as child:
                child.set_attribute("gen_ai.operation.name", "chat")
                child.set_attribute("gen_ai.request.model", "gpt-test")

        processor.force_flush(1000)

        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        child_span = next(span for span in spans if span["name"] == "chat")
        parent_span = next(span for span in spans if span["name"] == "agent")

        assert child_span["parent"] == parent_span["context"]

        provider.shutdown()


class TestOTLPHttpCalls:
    """Test that OTLP HTTP calls are made correctly."""

    def test_otlp_call_made_with_correct_url(self):
        """Verify the exporter calls the correct OTLP endpoint."""
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "http://test-endpoint.com/v1/traces",
                status=200,
            )

            processor = IntrospectionSpanProcessor(
                token="test-token",
                advanced=AdvancedOptions(
                    base_url="http://test-endpoint.com",
                ),
            )

            provider = TracerProvider()
            provider.add_span_processor(processor)
            tracer = provider.get_tracer("test")

            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.request.model", _MODEL)

            processor.force_flush(5000)

            assert len(rsps.calls) == 1
            assert (
                rsps.calls[0].request.url
                == "http://test-endpoint.com/v1/traces"
            )

            provider.shutdown()


class TestBaggagePropagation:
    """Test that IntrospectionSpanProcessor reads OTel baggage."""

    def _make_processor_and_provider(self):
        exporter = InMemorySpanExporter()
        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
            ),
        )
        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        return processor, provider, exporter

    def test_baggage_conversation_id_used_instead_of_autogenerated(self):
        """conversation ID from baggage is used, not auto-generated."""
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        ctx = baggage.set_baggage("gen_ai.conversation.id", "my-conv-123")
        token = context.attach(ctx)
        try:
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.request.model", _MODEL)
        finally:
            context.detach(token)

        processor.force_flush(1000)

        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert len(spans) == 1
        assert (
            spans[0]["attributes"]["gen_ai.conversation.id"] == "my-conv-123"
        )

        provider.shutdown()

    def test_baggage_agent_name_attached_to_span(self):
        """gen_ai.agent.name from baggage is attached to spans."""
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        ctx = baggage.set_baggage("gen_ai.agent.name", "my-bot")
        token = context.attach(ctx)
        try:
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.request.model", _MODEL)
        finally:
            context.detach(token)

        processor.force_flush(1000)

        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert len(spans) == 1
        assert spans[0]["attributes"]["gen_ai.agent.name"] == "my-bot"

        provider.shutdown()

    def test_existing_span_conversation_id_not_overwritten_by_baggage(self):
        """Baggage conversation ID overwrites even existing span attribute."""
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        ctx = baggage.set_baggage("gen_ai.conversation.id", "baggage-conv")
        token = context.attach(ctx)
        try:
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.conversation.id", "span-conv")
                span.set_attribute("gen_ai.request.model", _MODEL)
        finally:
            context.detach(token)

        processor.force_flush(1000)

        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert len(spans) == 1
        # Baggage takes precedence
        assert (
            spans[0]["attributes"]["gen_ai.conversation.id"] == "baggage-conv"
        )

        provider.shutdown()

    def test_no_baggage_autogenerates_conversation_id(self):
        """Without baggage, conversation ID is auto-generated."""
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("gen_ai.request.model", _MODEL)

        processor.force_flush(1000)

        spans = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert len(spans) == 1
        assert spans[0]["attributes"]["gen_ai.conversation.id"] == _CONV_ID

        provider.shutdown()

    def test_otlp_call_made_with_correct_headers(self):
        """Verify Authorization and User-Agent headers are sent."""
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "http://test-endpoint.com/v1/traces",
                status=200,
            )

            processor = IntrospectionSpanProcessor(
                token="my-secret-token",
                advanced=AdvancedOptions(
                    base_url="http://test-endpoint.com",
                    additional_headers={"X-Custom": "custom-value"},
                ),
            )

            provider = TracerProvider()
            provider.add_span_processor(processor)
            tracer = provider.get_tracer("test")

            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.request.model", _MODEL)

            processor.force_flush(5000)

            request = rsps.calls[0].request
            assert request.headers is not None
            assert request.headers["Authorization"] == "Bearer my-secret-token"
            assert "introspection-sdk" in request.headers["User-Agent"]
            assert request.headers["X-Custom"] == "custom-value"

            provider.shutdown()

    def test_identity_baggage_is_stamped_onto_the_span(self):
        """identify() has to reach spans, not just events.

        Without this the events emitted alongside a span carry the end user
        and the span does not, so the two disagree about who was acting.
        """
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        ctx = baggage.set_baggage("identity.user_id", "user_42")
        ctx = baggage.set_baggage("identity.anonymous_id", "anon_7", ctx)
        token = context.attach(ctx)
        try:
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.request.model", _MODEL)
        finally:
            context.detach(token)

        processor.force_flush(1000)
        (span_dict,) = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert span_dict["attributes"]["identity.user.id"] == "user_42"
        assert span_dict["attributes"]["identity.anonymous.id"] == "anon_7"

        provider.shutdown()

    def test_baggage_agent_identity_overrides_the_span_attribute(self):
        """Per-call agent identity beats a default stamped by the emitter."""
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        ctx = baggage.set_baggage("gen_ai.agent.name", "from-baggage")
        ctx = baggage.set_baggage("gen_ai.agent.id", "agent_9", ctx)
        token = context.attach(ctx)
        try:
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("gen_ai.request.model", _MODEL)
                span.set_attribute("gen_ai.agent.name", "on-span")
        finally:
            context.detach(token)

        processor.force_flush(1000)
        (span_dict,) = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert span_dict["attributes"]["gen_ai.agent.name"] == "from-baggage"
        assert span_dict["attributes"]["gen_ai.agent.id"] == "agent_9"

        provider.shutdown()

    def test_deprecated_system_key_is_stripped_and_operation_defaulted(self):
        """gen_ai.provider.name supersedes gen_ai.system.

        An emitter that still writes the pre-1.27 key would otherwise ship
        both. A span carrying messages but no operation name is a chat
        completion.
        """
        processor, provider, exporter = self._make_processor_and_provider()
        tracer = provider.get_tracer("test-tracer")

        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("gen_ai.provider.name", "anthropic")
            span.set_attribute("gen_ai.system", "anthropic")
            span.set_attribute("gen_ai.input.messages", "[]")

        processor.force_flush(1000)
        (span_dict,) = spans_to_dict(
            exporter.get_finished_spans(),
            parse_json_attributes=False,
            normalize_timestamps=True,
        )
        assert "gen_ai.system" not in span_dict["attributes"]
        assert span_dict["attributes"]["gen_ai.operation.name"] == "chat"

        provider.shutdown()


class TestOnEndHotPath:
    """`on_end` runs for every span the provider ends, kept or dropped."""

    def test_debug_message_is_not_built_when_the_level_discards_it(self):
        """The debug line must not be rendered at levels that drop it.

        It used to be built with an f-string, so the span name and the
        128-bit trace id were formatted on that path before `logging` had
        the chance to throw the record away -- which it does for every
        application that has not opted into DEBUG.
        """
        rendered = {"n": 0}

        class CountedName(str):
            def __str__(self) -> str:
                rendered["n"] += 1
                return "span"

            def __format__(self, _spec: str) -> str:
                rendered["n"] += 1
                return "span"

        span = ReadableSpan(
            name=CountedName("span"),
            context=SpanContext(
                trace_id=0x1234,
                span_id=0x5678,
                is_remote=False,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            ),
            attributes={},
        )
        processor = IntrospectionSpanProcessor(
            advanced=AdvancedOptions(span_exporter=InMemorySpanExporter()),
        )
        previous = sdk_logger.level
        sdk_logger.setLevel(logging.WARNING)
        try:
            processor.on_end(span)
        finally:
            sdk_logger.setLevel(previous)
            processor.shutdown()

        assert rendered["n"] == 0


class TestServiceNameResolution:
    """Where ``service.name`` on an exported span comes from.

    The logs surface has always read ``INTROSPECTION_SERVICE_NAME``. This
    processor did not, so a process that set the variable got named events
    and spans still carrying whatever the provider was built with.
    """

    def _export_one(self, **kwargs) -> ReadableSpan:
        exporter = InMemorySpanExporter()
        processor = IntrospectionSpanProcessor(
            advanced=AdvancedOptions(span_exporter=exporter), **kwargs
        )
        provider = TracerProvider(
            resource=Resource({"service.name": "caller-provider"}),
            id_generator=IncrementalIdGenerator(),
        )
        provider.add_span_processor(processor)
        with provider.get_tracer("t").start_as_current_span("s") as span:
            span.set_attribute("gen_ai.request.model", _MODEL)
        processor.force_flush(1000)
        (exported,) = exporter.get_finished_spans()
        provider.shutdown()
        return exported

    def test_the_environment_names_the_service(self, monkeypatch):
        monkeypatch.setenv("INTROSPECTION_SERVICE_NAME", "checkout-api")
        exported = self._export_one()
        assert exported.resource.attributes["service.name"] == "checkout-api"

    def test_an_explicit_name_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv("INTROSPECTION_SERVICE_NAME", "from-env")
        exported = self._export_one(service_name="from-argument")
        assert exported.resource.attributes["service.name"] == "from-argument"

    def test_naming_nothing_leaves_the_provider_alone(self, monkeypatch):
        # The processor must not relabel a provider the caller built and
        # named itself.
        monkeypatch.delenv("INTROSPECTION_SERVICE_NAME", raising=False)
        exported = self._export_one()
        assert (
            exported.resource.attributes["service.name"] == "caller-provider"
        )


def _flush_harness(debounce_ms: int):
    """A processor whose scheduled flush is far away, so anything that
    gets exported can only have come from the eager path."""
    exporter = InMemorySpanExporter()
    processor = IntrospectionSpanProcessor(
        token="test-token",
        advanced=AdvancedOptions(
            span_exporter=exporter,
            flush_interval_ms=60_000,
            message_flush_debounce_ms=debounce_ms,
        ),
    )
    provider = TracerProvider(id_generator=IncrementalIdGenerator())
    provider.add_span_processor(processor)
    return exporter, provider, processor


def _record_message(provider) -> None:
    provider.get_tracer("test").start_span(
        "chat", attributes={"gen_ai.request.model": _MODEL}
    ).end()


class TestEagerMessageFlush:
    """The debounced flush that gets a logged message out without waiting."""

    _harness = staticmethod(_flush_harness)
    _record_message = staticmethod(_record_message)

    def test_exports_without_waiting_for_the_scheduled_flush(self):
        exporter, provider, processor = self._harness(20)
        try:
            self._record_message(provider)
            assert exporter.get_finished_spans() == ()

            deadline = time.monotonic() + 5
            while (
                not exporter.get_finished_spans()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert len(exporter.get_finished_spans()) == 1
        finally:
            processor.shutdown()

    def test_disabled_leaves_the_span_to_the_scheduled_flush(self):
        exporter, provider, processor = self._harness(0)
        try:
            self._record_message(provider)
            time.sleep(0.3)
            assert exporter.get_finished_spans() == ()
        finally:
            processor.shutdown()

    def test_batches_a_burst_into_one_export(self):
        exporter, provider, processor = self._harness(50)
        try:
            for _ in range(5):
                self._record_message(provider)

            deadline = time.monotonic() + 5
            while (
                len(exporter.get_finished_spans()) < 5
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            # All five arrive, and they arrive together -- the ingest processor
            # deduplicates provider spans sharing a response id only within a
            # batch.
            assert len(exporter.get_finished_spans()) == 5
        finally:
            processor.shutdown()

    def test_ignores_infrastructure_spans(self):
        exporter, provider, processor = self._harness(20)
        try:
            provider.get_tracer("test").start_span("GET /health").end()
            time.sleep(0.3)
            assert exporter.get_finished_spans() == ()
        finally:
            processor.shutdown()

    def test_debounce_is_capped_by_the_flush_interval(self):
        """A span stream arriving faster than the debounce still exports."""
        exporter = InMemorySpanExporter()
        processor = IntrospectionSpanProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                # Cap well below the debounce, so only the cap can fire.
                flush_interval_ms=100,
                message_flush_debounce_ms=10_000,
            ),
        )
        provider = TracerProvider(id_generator=IncrementalIdGenerator())
        provider.add_span_processor(processor)
        try:
            self._record_message(provider)
            deadline = time.monotonic() + 5
            while (
                not exporter.get_finished_spans()
                and time.monotonic() < deadline
            ):
                self._record_message(provider)
                time.sleep(0.01)
            assert exporter.get_finished_spans()
        finally:
            processor.shutdown()

    def test_worker_thread_is_a_daemon(self):
        """A pending flush must never hold up interpreter exit."""
        _, provider, processor = self._harness(50_000)
        try:
            self._record_message(provider)
            worker = processor._flush_worker
            assert worker is not None
            assert worker.daemon is True
        finally:
            processor.shutdown()


class _HoldableProcessor:
    """Stands in for the batch processor, with a flush we can hold open.

    What matters here is the order in which the wrapped processor is called,
    not what an exporter received: an eager flush that is still inside the
    exporter has already taken its spans off the queue, so a shutdown that
    races it destroys the exporter with those spans in flight and the drain
    has nothing left to find.
    """

    def __init__(self) -> None:
        self.flush_entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def on_start(self, span, parent_context=None) -> None:
        pass

    def on_end(self, span) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.calls.append("flush_start")
        self.flush_entered.set()
        self.release.wait(10)
        self.calls.append("flush_end")
        return True

    def shutdown(self) -> None:
        self.calls.append("shutdown")


class TestShutdownWithAFlushInFlight:
    """`shutdown()` against the eager worker mid-flush."""

    @staticmethod
    def _harness():
        exporter, provider, processor = _flush_harness(10)
        # The real batch processor is not wanted here, only the ordering, so
        # retire it before putting the stand-in in its place.
        processor._span_processor.shutdown()
        inner = _HoldableProcessor()
        processor._span_processor = inner
        return inner, provider, processor

    def test_an_in_flight_flush_finishes_before_the_processor_closes(self):
        inner, provider, processor = self._harness()
        _record_message(provider)
        assert inner.flush_entered.wait(5)

        releaser = threading.Timer(0.2, inner.release.set)
        releaser.start()
        try:
            processor.shutdown()
        finally:
            releaser.cancel()
            inner.release.set()

        assert inner.calls == ["flush_start", "flush_end", "shutdown"]
        assert processor._flush_worker is not None
        assert not processor._flush_worker.is_alive()

    def test_a_flush_that_never_returns_does_not_hold_shutdown_open(
        self, monkeypatch
    ):
        """A wedged exporter must not keep the process from exiting."""
        monkeypatch.setattr(
            span_processor_module, "_FLUSH_JOIN_TIMEOUT_S", 0.1
        )
        inner, provider, processor = self._harness()
        _record_message(provider)
        assert inner.flush_entered.wait(5)

        started = time.monotonic()
        try:
            processor.shutdown()
            elapsed = time.monotonic() - started
        finally:
            inner.release.set()

        assert elapsed < 2
        assert inner.calls == ["flush_start", "shutdown"]


class TestForkedProcesses:
    """Pre-forking servers initialize the SDK in the parent.

    Threads do not survive `fork()`, so the child inherits a handle to a
    worker that no longer runs. Left alone, the child never starts a
    replacement and every message it logs waits for the scheduled flush.
    """

    def test_the_reset_drops_a_lock_the_child_could_never_release(self):
        """A fork can land while another thread holds the flush lock."""
        _, _, processor = _flush_harness(50_000)
        try:
            inherited = processor._flush_lock
            inherited.acquire()
            processor._flush_worker = threading.current_thread()

            processor._reset_flush_state_after_fork()

            assert not processor._flush_lock.locked()
            assert processor._flush_lock is not inherited
            assert processor._flush_worker is None
            assert processor._flush_due_at is None
            assert processor._flush_hard_deadline is None
            inherited.release()
        finally:
            processor.shutdown()

    def test_a_stale_worker_handle_does_not_block_a_new_one(self):
        """The pid re-check covers a fork the at-fork hook did not see."""
        _, provider, processor = _flush_harness(50_000)
        try:
            _record_message(provider)
            inherited = processor._flush_worker
            assert inherited is not None

            processor._flush_worker_pid = -1
            _record_message(provider)

            assert processor._flush_worker is not inherited
            assert processor._flush_worker.is_alive()
        finally:
            processor.shutdown()

    @pytest.mark.skipif(
        not hasattr(os, "fork"), reason="platform has no fork()"
    )
    def test_a_forked_child_still_flushes_eagerly(self):
        exporter, provider, processor = _flush_harness(20)
        try:
            _record_message(provider)
            deadline = time.monotonic() + 5
            while (
                not exporter.get_finished_spans()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert len(exporter.get_finished_spans()) == 1

            pid = os.fork()
            if pid == 0:
                # The child reports through its exit code and leaves with
                # `os._exit`, so it never runs the test session's teardown.
                code = 1
                try:
                    if processor._flush_worker is None:
                        _record_message(provider)
                        child_deadline = time.monotonic() + 10
                        while (
                            len(exporter.get_finished_spans()) < 2
                            and time.monotonic() < child_deadline
                        ):
                            time.sleep(0.01)
                        if len(exporter.get_finished_spans()) == 2:
                            code = 0
                except BaseException:
                    code = 1
                finally:
                    os._exit(code)

            _, status = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        finally:
            processor.shutdown()
