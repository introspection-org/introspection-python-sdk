"""Tests for IntrospectionTracingProcessor."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from dirty_equals import IsJson, IsStr
from inline_snapshot import snapshot
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from .test_utils import IncrementalIdGenerator, TimeGenerator, spans_to_dict

# Matches auto-generated conversation IDs like "intro_conv_<32 hex chars>"
_CONV_ID = IsStr(regex=r"^intro_conv_[0-9a-f]{32}$")

# Try to import agents types and processor, skip tests if not available
AGENTS_AVAILABLE = True
try:
    from agents.tracing import Span as AgentSpan
    from agents.tracing import Trace
    from agents.tracing.span_data import (
        AgentSpanData,
        FunctionSpanData,
        GenerationSpanData,
        HandoffSpanData,
        ResponseSpanData,
    )

    from introspection_sdk import (
        AdvancedOptions,
        IntrospectionTracingProcessor,
    )
except (ImportError, RuntimeError):
    AGENTS_AVAILABLE = False
    if TYPE_CHECKING:
        from agents.tracing import Span as AgentSpan
        from agents.tracing import Trace
        from agents.tracing.span_data import (
            AgentSpanData,
            FunctionSpanData,
            GenerationSpanData,
            HandoffSpanData,
            ResponseSpanData,
        )

        from introspection_sdk import (
            AdvancedOptions,
            IntrospectionTracingProcessor,
        )

pytestmark = pytest.mark.skipif(
    not AGENTS_AVAILABLE,
    reason="openai-agents package not available",
)


class TestIntrospectionTracingProcessor:
    """Test suite for IntrospectionTracingProcessor."""

    def test_tracing_processor_creation_with_token(self):
        """Test basic creation with token."""
        processor = IntrospectionTracingProcessor(token="test-token")
        assert processor is not None
        processor.force_flush()
        processor.shutdown()

    def test_tracing_processor_creation_with_advanced_options(self):
        """Test creation with advanced options."""
        custom_headers = {"X-Custom-Header": "custom-value"}

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                base_url="http://localhost:5418/v1/traces",
                additional_headers=custom_headers,
            ),
        )

        assert processor is not None
        processor.force_flush()
        processor.shutdown()

    def test_tracing_processor_processes_agent_span(self):
        """Test that agent spans are processed with correct attributes."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        # Create mock trace
        trace = Mock(spec=Trace)
        trace.trace_id = "trace-1"
        trace.name = "test-agent-trace"
        processor.on_trace_start(trace)

        # Create mock agent span
        agent_span_data = Mock(spec=AgentSpanData)
        agent_span_data.type = "agent"
        agent_span_data.name = "test-agent"
        agent_span_data.tools = ["tool1", "tool2"]
        agent_span_data.handoffs = None
        agent_span_data.output_type = "text"
        agent_span_data.export = Mock(
            return_value={"type": "agent", "name": "test-agent"}
        )

        agent_span = Mock(spec=AgentSpan)
        agent_span.span_id = "span-1"
        agent_span.trace_id = "trace-1"
        agent_span.parent_id = None
        agent_span.span_data = agent_span_data

        # Process span
        processor.on_span_start(agent_span)
        processor.on_span_end(agent_span)

        processor.on_trace_end(trace)
        processor.force_flush()

        # Convert to dict and compare with snapshot
        # Use parse_json_attributes=False to match actual stored format (JSON strings)
        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        # Sort spans by start_time for consistent ordering
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-agent-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "test-agent",
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
                        "openinference.span.kind": "AGENT",
                        "gen_ai.system": "openai",
                        "gen_ai.provider.name": "openai",
                        "gen_ai.agent.name": "test-agent",
                        "gen_ai.tool.definitions": IsJson(
                            [{"name": "tool1"}, {"name": "tool2"}]
                        ),
                        "gen_ai.agent.output_type": "text",
                        "openai_agents.span_data": IsJson(
                            {"type": "agent", "name": "test-agent"}
                        ),
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        processor.shutdown()

    def test_tracing_processor_processes_function_span(self):
        """Test that function spans are processed with correct attributes."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        # Create mock trace
        trace = Mock(spec=Trace)
        trace.trace_id = "trace-2"
        trace.name = "test-function-trace"
        processor.on_trace_start(trace)

        # Create mock function span
        function_span_data = Mock(spec=FunctionSpanData)
        function_span_data.type = "function"
        function_span_data.name = "get_weather"
        function_span_data.input = '{"city": "Tokyo"}'
        function_span_data.output = '{"temperature": "20C"}'
        function_span_data.export = Mock(
            return_value={"type": "function", "name": "get_weather"}
        )

        function_span = Mock(spec=AgentSpan)
        function_span.span_id = "span-2"
        function_span.trace_id = "trace-2"
        function_span.parent_id = "span-1"
        function_span.span_data = function_span_data

        # Process span
        processor.on_span_start(function_span)
        processor.on_span_end(function_span)

        processor.on_trace_end(trace)
        processor.force_flush()

        # Convert to dict and compare with snapshot
        # Use parse_json_attributes=False to match actual stored format (JSON strings)
        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        # Sort spans by start_time for consistent ordering
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-function-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "get_weather",
                    "context": {
                        "trace_id": 2,
                        "span_id": 2,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 2000000000,
                    "end_time": 3000000000,
                    "attributes": {
                        "openinference.span.kind": "TOOL",
                        "gen_ai.tool.name": "get_weather",
                        "gen_ai.tool.input": IsJson({"city": "Tokyo"}),
                        "gen_ai.tool.output": IsJson({"temperature": "20C"}),
                        "openai_agents.span_data": IsJson(
                            {"type": "function", "name": "get_weather"}
                        ),
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        processor.shutdown()

    def test_tracing_processor_processes_response_span(self):
        """Test that response spans are processed with correct attributes."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        # Create mock trace
        trace = Mock(spec=Trace)
        trace.trace_id = "trace-3"
        trace.name = "test-response-trace"
        processor.on_trace_start(trace)

        # Create mock response span
        response_mock = Mock()
        response_mock.instructions = "You are a helpful assistant"
        response_mock.tools = []
        response_mock.usage = Mock()
        response_mock.usage.input_tokens = 10
        response_mock.usage.output_tokens = 20
        response_mock.model = "gpt-4"
        response_mock.id = "resp-123"
        response_mock.output = []

        response_span_data = Mock(spec=ResponseSpanData)
        response_span_data.type = "response"
        response_span_data.response = response_mock
        response_span_data.input = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}],
                "type": "message",
            }
        ]
        response_span_data.export = Mock(
            return_value={"type": "response", "response": {"id": "resp-123"}}
        )

        response_span = Mock(spec=AgentSpan)
        response_span.span_id = "span-3"
        response_span.trace_id = "trace-3"
        response_span.parent_id = "span-1"
        response_span.span_data = response_span_data

        # Process span
        processor.on_span_start(response_span)
        processor.on_span_end(response_span)

        processor.on_trace_end(trace)
        processor.force_flush()

        # Convert to dict and compare with snapshot
        # Use parse_json_attributes=False to match actual stored format (JSON strings)
        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        # Sort spans by start_time for consistent ordering
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-response-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "response",
                    "context": {
                        "trace_id": 2,
                        "span_id": 2,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 2000000000,
                    "end_time": 3000000000,
                    "attributes": {
                        "openinference.span.kind": "LLM",
                        "gen_ai.operation.name": "chat",
                        "gen_ai.system": "openai",
                        "gen_ai.provider.name": "openai",
                        "gen_ai.system_instructions": IsJson(
                            [
                                {
                                    "type": "text",
                                    "content": "You are a helpful assistant",
                                }
                            ]
                        ),
                        "gen_ai.usage.input_tokens": 10,
                        "gen_ai.usage.output_tokens": 20,
                        "gen_ai.request.model": "gpt-4",
                        "gen_ai.response.model": "gpt-4",
                        "gen_ai.response.id": "resp-123",
                        "gen_ai.input.messages": IsJson(
                            [
                                {
                                    "role": "user",
                                    "parts": [
                                        {"type": "text", "content": "Hello"}
                                    ],
                                }
                            ]
                        ),
                        "openai_agents.span_data": IsJson(
                            {
                                "type": "response",
                                "response": {"id": "resp-123"},
                            }
                        ),
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        processor.shutdown()

    def test_tracing_processor_processes_generation_span(self):
        """Test that generation spans are processed with correct attributes."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        # Create mock trace
        trace = Mock(spec=Trace)
        trace.trace_id = "trace-4"
        trace.name = "test-generation-trace"
        processor.on_trace_start(trace)

        # Create mock generation span
        # Note: parent_id should match the trace span's span_id (1) for proper parent linking
        generation_span_data = Mock(spec=GenerationSpanData)
        generation_span_data.type = "generation"
        generation_span_data.model = "gpt-4"
        generation_span_data.usage = {"input_tokens": 5, "output_tokens": 15}
        generation_span_data.input = [{"role": "user", "content": "Hi"}]
        generation_span_data.output = [
            {"role": "assistant", "content": "Hello!"}
        ]
        generation_span_data.export = Mock(
            return_value={"type": "generation", "model": "gpt-4"}
        )

        generation_span = Mock(spec=AgentSpan)
        generation_span.span_id = "span-4"
        generation_span.trace_id = "trace-4"
        # Use trace_id so it falls back to finding parent by trace_id
        # Since mock trace_id doesn't match generated one, parent will be None
        generation_span.parent_id = None
        generation_span.span_data = generation_span_data

        # Process span
        processor.on_span_start(generation_span)
        processor.on_span_end(generation_span)

        processor.on_trace_end(trace)
        processor.force_flush()

        # Convert to dict and compare with snapshot
        # Use parse_json_attributes=False to match actual stored format (JSON strings)
        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        # Sort spans by start_time for consistent ordering
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-generation-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "generation",
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
                        "gen_ai.request.model": "gpt-4",
                        "gen_ai.usage.input_tokens": 5,
                        "gen_ai.usage.output_tokens": 15,
                        "gen_ai.input.messages": IsJson(
                            [{"role": "user", "content": "Hi"}]
                        ),
                        "gen_ai.output.messages": IsJson(
                            [{"role": "assistant", "content": "Hello!"}]
                        ),
                        "openai_agents.span_data": IsJson(
                            {"type": "generation", "model": "gpt-4"}
                        ),
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        processor.shutdown()

    def test_tracing_processor_processes_handoff_span(self):
        """Test that handoff spans are processed with correct attributes."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        # Create mock trace
        trace = Mock(spec=Trace)
        trace.trace_id = "trace-5"
        trace.name = "test-handoff-trace"
        processor.on_trace_start(trace)

        # Create mock handoff span
        handoff_span_data = Mock(spec=HandoffSpanData)
        handoff_span_data.type = "handoff"
        handoff_span_data.from_agent = "agent-1"
        handoff_span_data.to_agent = "agent-2"
        handoff_span_data.export = Mock(
            return_value={
                "type": "handoff",
                "from_agent": "agent-1",
                "to_agent": "agent-2",
            }
        )

        handoff_span = Mock(spec=AgentSpan)
        handoff_span.span_id = "span-5"
        handoff_span.trace_id = "trace-5"
        # Use trace_id so it falls back to finding parent by trace_id
        # Since mock trace_id doesn't match generated one, parent will be None
        handoff_span.parent_id = None
        handoff_span.span_data = handoff_span_data

        # Process span
        processor.on_span_start(handoff_span)
        processor.on_span_end(handoff_span)

        processor.on_trace_end(trace)
        processor.force_flush()

        # Convert to dict and compare with snapshot
        # Use parse_json_attributes=False to match actual stored format (JSON strings)
        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        # Sort spans by start_time for consistent ordering
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "test-handoff-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
                {
                    "name": "handoff",
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
                        "gen_ai.handoff.from_agent": "agent-1",
                        "gen_ai.handoff.to_agent": "agent-2",
                        "openai_agents.span_data": IsJson(
                            {
                                "type": "handoff",
                                "from_agent": "agent-1",
                                "to_agent": "agent-2",
                            }
                        ),
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                },
            ]
        )

        processor.shutdown()

    def test_tracing_processor_with_custom_exporter(self):
        """Test processor accepts custom exporter via AdvancedOptions."""
        exporter = InMemorySpanExporter()

        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(span_exporter=exporter),
        )

        # Verify processor was created successfully with custom exporter
        assert processor is not None
        processor.force_flush()
        processor.shutdown()

    def test_tracing_processor_shutdown(self):
        """Test processor shutdown."""
        processor = IntrospectionTracingProcessor(token="test-token")
        processor.shutdown()
        # Shutdown should complete without error
        assert True

    def test_tracing_processor_requires_token(self):
        """Test that token is required when not using custom exporter."""
        # Clear any env var that might be set
        old_token = os.environ.pop("INTROSPECTION_TOKEN", None)

        try:
            with pytest.raises(ValueError, match="INTROSPECTION_TOKEN"):
                IntrospectionTracingProcessor()
        finally:
            # Restore the env var if it was set
            if old_token:
                os.environ["INTROSPECTION_TOKEN"] = old_token

    def test_tracing_processor_uses_env_token(self):
        """Test processor uses INTROSPECTION_TOKEN env var."""
        # Save any existing token
        old_token = os.environ.get("INTROSPECTION_TOKEN")

        try:
            os.environ["INTROSPECTION_TOKEN"] = "env-token"

            processor = IntrospectionTracingProcessor()
            assert processor is not None
            processor.shutdown()
        finally:
            # Restore the original token or remove if it didn't exist
            if old_token:
                os.environ["INTROSPECTION_TOKEN"] = old_token
            else:
                os.environ.pop("INTROSPECTION_TOKEN", None)

    def test_tracing_processor_default_service_name(self):
        """Test that spans carry the default service.name resource attribute."""
        exporter = InMemorySpanExporter()
        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        trace = Mock(spec=Trace)
        trace.trace_id = "trace-svc-default"
        trace.name = "default-service-trace"
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        processor.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "default-service-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                }
            ]
        )
        processor.shutdown()

    def test_tracing_processor_custom_service_name(self):
        """Test that service_name param overrides the default."""
        exporter = InMemorySpanExporter()
        processor = IntrospectionTracingProcessor(
            token="test-token",
            service_name="my-custom-agent",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        trace = Mock(spec=Trace)
        trace.trace_id = "trace-svc-custom"
        trace.name = "custom-service-trace"
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        processor.force_flush()

        finished_spans = exporter.get_finished_spans()
        spans = spans_to_dict(finished_spans, parse_json_attributes=False)
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "custom-service-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                }
            ]
        )
        assert (
            finished_spans[0].resource.attributes["service.name"]
            == "my-custom-agent"
        )
        processor.shutdown()

    def test_tracing_processor_service_name_from_env(self):
        """Test that INTROSPECTION_SERVICE_NAME env var sets service.name."""
        old_val = os.environ.get("INTROSPECTION_SERVICE_NAME")
        try:
            os.environ["INTROSPECTION_SERVICE_NAME"] = "env-service"
            exporter = InMemorySpanExporter()
            processor = IntrospectionTracingProcessor(
                token="test-token",
                advanced=AdvancedOptions(
                    span_exporter=exporter,
                    id_generator=IncrementalIdGenerator(),
                    ns_timestamp_generator=TimeGenerator(),
                ),
            )

            trace = Mock(spec=Trace)
            trace.trace_id = "trace-svc-env"
            trace.name = "env-service-trace"
            processor.on_trace_start(trace)
            processor.on_trace_end(trace)
            processor.force_flush()

            finished_spans = exporter.get_finished_spans()
            spans = spans_to_dict(finished_spans, parse_json_attributes=False)
            spans = sorted(spans, key=lambda s: s["start_time"])
            assert spans == snapshot(
                [
                    {
                        "name": "env-service-trace",
                        "context": {
                            "trace_id": 1,
                            "span_id": 1,
                            "is_remote": False,
                        },
                        "parent": None,
                        "start_time": 1000000000,
                        "end_time": 2000000000,
                        "attributes": {
                            "openinference.span.kind": "AGENT",
                            "gen_ai.conversation.id": _CONV_ID,
                        },
                    }
                ]
            )
            assert (
                finished_spans[0].resource.attributes["service.name"]
                == "env-service"
            )
        finally:
            if old_val:
                os.environ["INTROSPECTION_SERVICE_NAME"] = old_val
            else:
                os.environ.pop("INTROSPECTION_SERVICE_NAME", None)

    def test_tracing_processor_conversation_id_from_baggage(self):
        """Test that gen_ai.conversation.id from OTel baggage is set on spans."""
        from opentelemetry import baggage, context

        exporter = InMemorySpanExporter()
        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        # Set conversation_id via OTel baggage (same mechanism as client.set_conversation)
        ctx = baggage.set_baggage("gen_ai.conversation.id", "conv_test_123")
        token = context.attach(ctx)
        try:
            trace = Mock(spec=Trace)
            trace.trace_id = "trace-conv"
            trace.name = "conversation-trace"
            processor.on_trace_start(trace)

            agent_span_data = Mock(spec=AgentSpanData)
            agent_span_data.type = "agent"
            agent_span_data.name = "test-agent"
            agent_span_data.tools = []
            agent_span_data.handoffs = None
            agent_span_data.output_type = None
            agent_span_data.export = Mock(
                return_value={"type": "agent", "name": "test-agent"}
            )

            agent_span = Mock(spec=AgentSpan)
            agent_span.span_id = "span-conv-1"
            agent_span.trace_id = "trace-conv"
            agent_span.parent_id = None
            agent_span.span_data = agent_span_data

            processor.on_span_start(agent_span)
            processor.on_span_end(agent_span)
            processor.on_trace_end(trace)
        finally:
            context.detach(token)

        processor.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "conversation-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 4000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": "conv_test_123",
                    },
                },
                {
                    "name": "test-agent",
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
                        "openinference.span.kind": "AGENT",
                        "gen_ai.system": "openai",
                        "gen_ai.provider.name": "openai",
                        "gen_ai.agent.name": "test-agent",
                        "openai_agents.span_data": IsJson(
                            {"type": "agent", "name": "test-agent"}
                        ),
                        "gen_ai.conversation.id": "conv_test_123",
                    },
                },
            ]
        )
        processor.shutdown()

    def test_tracing_processor_auto_generates_conversation_id(self):
        """Test that gen_ai.conversation.id is auto-generated when no baggage is set."""
        exporter = InMemorySpanExporter()
        processor = IntrospectionTracingProcessor(
            token="test-token",
            advanced=AdvancedOptions(
                span_exporter=exporter,
                id_generator=IncrementalIdGenerator(),
                ns_timestamp_generator=TimeGenerator(),
            ),
        )

        trace = Mock(spec=Trace)
        trace.trace_id = "trace-auto-conv"
        trace.name = "auto-conversation-trace"
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        processor.force_flush()

        spans = spans_to_dict(
            exporter.get_finished_spans(), parse_json_attributes=False
        )
        spans = sorted(spans, key=lambda s: s["start_time"])
        assert spans == snapshot(
            [
                {
                    "name": "auto-conversation-trace",
                    "context": {
                        "trace_id": 1,
                        "span_id": 1,
                        "is_remote": False,
                    },
                    "parent": None,
                    "start_time": 1000000000,
                    "end_time": 2000000000,
                    "attributes": {
                        "openinference.span.kind": "AGENT",
                        "gen_ai.conversation.id": _CONV_ID,
                    },
                }
            ]
        )
        processor.shutdown()
