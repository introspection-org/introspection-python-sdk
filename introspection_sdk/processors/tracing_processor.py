"""OpenAI Agents TracingProcessor for Introspection SDK.

Forwards OpenAI agent traces to the backend via OTLP with OTel Gen AI semantic
convention attributes.
"""

from __future__ import annotations

__all__ = ["IntrospectionTracingProcessor"]

import json
import os
import uuid
from typing import TYPE_CHECKING, cast
from urllib.parse import urljoin

from opentelemetry import baggage
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as OTLPHTTPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
)

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.converters.openai import (
    convert_responses_inputs_to_semconv,
    convert_responses_outputs_to_semconv,
)
from introspection_sdk.schemas.genai import (
    SystemInstruction,
    ToolDefinition,
)
from introspection_sdk.utils import logger, platform_is_emscripten
from introspection_sdk.version import VERSION

if TYPE_CHECKING:
    from openai.types.responses import FunctionTool, ResponseReasoningItem
else:
    try:
        from openai.types.responses import FunctionTool, ResponseReasoningItem
    except ImportError:
        FunctionTool = None
        ResponseReasoningItem = None

# OpenAI agents tracing types (optional dependency).
# When not installed, the module still loads but the class raises on __init__.
HAS_OPENAI_AGENTS = True
try:
    from agents.tracing import Span as AgentSpan
    from agents.tracing import Trace, TracingProcessor
    from agents.tracing.span_data import (
        AgentSpanData,
        FunctionSpanData,
        GenerationSpanData,
        HandoffSpanData,
        ResponseSpanData,
        SpanData,
    )
except ImportError:
    HAS_OPENAI_AGENTS = False
    TracingProcessor = object  # type: ignore[assignment,misc]


class IntrospectionTracingProcessor(TracingProcessor):
    """Forwards OpenAI agent traces to Introspection backend via OTLP.

    Extracts OTel Gen AI semantic convention attributes from span data:

    - Agent spans: ``gen_ai.agent.name``, ``gen_ai.agent.id``
    - Function spans: ``gen_ai.tool.name``
    - Response spans: ``gen_ai.system_instructions``, ``gen_ai.input/output.messages``,
      ``gen_ai.usage.input/output_tokens``, ``gen_ai.tool.definitions``

    Args:
        token: Introspection API token. Falls back to the
            ``INTROSPECTION_TOKEN`` environment variable.
        advanced: Optional :class:`AdvancedOptions` for custom exporters,
            headers, batch settings, etc.

    Raises:
        ValueError: If neither ``token`` nor ``INTROSPECTION_TOKEN`` is set.

    Example::

        from agents import Agent, Runner
        processor = IntrospectionTracingProcessor(token="my-token")
        agent = Agent(name="my-agent", instructions="You are helpful.")
        result = Runner.run_sync(agent, "Hello!", run_config=RunConfig(
            tracing_processors=[processor],
        ))
        processor.force_flush()
        processor.shutdown()
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        service_name: str | None = None,
        advanced: AdvancedOptions | None = None,
    ):
        if not HAS_OPENAI_AGENTS:
            raise RuntimeError(
                "IntrospectionTracingProcessor requires the `openai-agents` package.\n"
                "Install it with: pip install 'introspection-sdk[openai-agents]'"
            )
        # Use defaults if not provided
        self._advanced = advanced or AdvancedOptions()

        if self._advanced.span_exporter:
            # Use provided exporter (for testing)
            exporter = self._advanced.span_exporter
        else:
            # Create default OTLP exporter
            base_url = self._advanced.base_url or os.getenv(
                "INTROSPECTION_BASE_URL", "https://otel.introspection.dev"
            )
            token = token or os.getenv("INTROSPECTION_TOKEN")
            if not token:
                raise ValueError("INTROSPECTION_TOKEN is not set")

            headers = {
                "User-Agent": f"introspection-sdk/{VERSION}",
                "Authorization": f"Bearer {token}",
                **(self._advanced.additional_headers or {}),
            }

            endpoint = (
                base_url
                if base_url.endswith("/v1/traces")
                else urljoin(base_url, "/v1/traces")
            )
            logger.info(f"IntrospectionTracingProcessor endpoint: {endpoint}")

            exporter = OTLPHTTPSpanExporter(
                endpoint=endpoint,
                compression=Compression.NoCompression,
                headers=headers,
            )

        _service_name = service_name or os.getenv(
            "INTROSPECTION_SERVICE_NAME", "openai-agents"
        )
        resource = Resource.create({"service.name": _service_name})
        self._tracer_provider = TracerProvider(
            resource=resource,
            id_generator=self._advanced.id_generator,
        )
        # Use SimpleSpanProcessor for sequential export when max_batch_size=1
        # or on emscripten (no threading). This ensures each span is exported
        # immediately on end(), which is required for multi-turn conversations
        # where each turn must be ingested before the next arrives.
        # Default to sequential export for dev/staging tokens.
        max_batch = self._advanced.max_batch_size
        if (
            max_batch is None
            and token
            and (
                token.startswith("intro_dev")
                or token.startswith("intro_staging")
            )
        ):
            max_batch = 1
        use_simple = platform_is_emscripten() or max_batch == 1
        if use_simple:
            self._tracer_provider.add_span_processor(
                SimpleSpanProcessor(exporter)
            )
        else:
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    schedule_delay_millis=self._advanced.flush_interval_ms,
                    max_export_batch_size=max_batch,
                )
            )

        self._tracer = self._tracer_provider.get_tracer(
            "openai-agents", VERSION
        )
        self._spans: dict[str, otel_trace.Span] = {}
        self._conversation_ids: dict[str, str] = {}

    def _apply_baggage_context(self, otel_span: otel_trace.Span) -> None:
        """Read gen_ai context from OTel baggage and set on span.

        Allows callers to propagate conversation ID and agent identity into
        agent spans by setting baggage via :meth:`IntrospectionClient.set_conversation`
        or :meth:`IntrospectionClient.set_agent` before running the agent.

        Args:
            otel_span: The OTel span to enrich with baggage attributes.
        """
        conversation_id = baggage.get_baggage("gen_ai.conversation.id")
        if conversation_id:
            otel_span.set_attribute(
                "gen_ai.conversation.id", str(conversation_id)
            )
        agent_name = baggage.get_baggage("gen_ai.agent.name")
        if agent_name:
            otel_span.set_attribute("gen_ai.agent.name", str(agent_name))
        agent_id = baggage.get_baggage("gen_ai.agent.id")
        if agent_id:
            otel_span.set_attribute("gen_ai.agent.id", str(agent_id))

    def on_trace_start(self, trace: Trace | None = None) -> None:
        """Start an OTel span for the given agent trace.

        Args:
            trace: The OpenAI agent trace that is starting.
        """
        if trace:
            start_time = self._advanced.ns_timestamp_generator()
            otel_span = self._tracer.start_span(
                trace.name, start_time=start_time
            )
            otel_span.set_attribute("openinference.span.kind", "AGENT")
            self._apply_baggage_context(otel_span)
            # Determine conversation ID: use baggage if set, otherwise auto-generate
            conversation_id = baggage.get_baggage("gen_ai.conversation.id")
            if not conversation_id:
                conversation_id = f"intro_conv_{uuid.uuid4().hex}"
                otel_span.set_attribute(
                    "gen_ai.conversation.id", conversation_id
                )
            self._conversation_ids[trace.trace_id] = str(conversation_id)
            self._spans[trace.trace_id] = otel_span

    def on_trace_end(self, trace: Trace | None = None) -> None:
        """End the OTel span for the given agent trace.

        Args:
            trace: The OpenAI agent trace that has ended.
        """
        if trace:
            otel_span = self._spans.pop(trace.trace_id, None)
            self._conversation_ids.pop(trace.trace_id, None)
            if otel_span:
                end_time = self._advanced.ns_timestamp_generator()
                otel_span.end(end_time=end_time)

    def on_span_start(self, span: AgentSpan[SpanData] | None = None) -> None:
        """Start an OTel child span for the given agent span.

        Derives the span name from ``span_data.name`` for agent/function spans,
        or ``span_data.type`` for other span types.

        Args:
            span: The OpenAI agent span that is starting.
        """
        if span:
            parent_id = span.parent_id or span.trace_id
            parent = self._spans.get(parent_id)
            context = (
                otel_trace.set_span_in_context(parent) if parent else None
            )

            span_data = span.span_data
            if isinstance(span_data, AgentSpanData | FunctionSpanData):
                name = span_data.name
            else:
                name = span_data.type
            start_time = self._advanced.ns_timestamp_generator()
            otel_span = self._tracer.start_span(
                name, context=context, start_time=start_time
            )
            self._spans[span.span_id] = otel_span

    def on_span_end(self, span: AgentSpan[SpanData] | None = None) -> None:
        """End the OTel span, extracting gen_ai attributes by span type.

        Dispatches to ``_process_agent_span``, ``_process_function_span``,
        ``_process_response_span``, ``_process_generation_span``, or
        ``_process_handoff_span`` based on ``span_data.type``.

        Args:
            span: The OpenAI agent span that has ended.
        """
        if span:
            otel_span = self._spans.pop(span.span_id, None)
            if otel_span:
                span_data = span.span_data
                span_type = span_data.type

                # Extract gen_ai.* attributes based on span type
                # Use type casts to help type checker narrow union types
                if span_type == "agent":
                    self._process_agent_span(
                        otel_span,
                        cast(AgentSpan[AgentSpanData], span),
                        cast(AgentSpanData, span_data),
                    )
                elif span_type == "function":
                    self._process_function_span(
                        otel_span,
                        cast(AgentSpan[FunctionSpanData], span),
                        cast(FunctionSpanData, span_data),
                    )
                elif span_type == "response":
                    self._process_response_span(
                        otel_span,
                        cast(AgentSpan[ResponseSpanData], span),
                        cast(ResponseSpanData, span_data),
                    )
                elif span_type == "generation":
                    self._process_generation_span(
                        otel_span,
                        cast(AgentSpan[GenerationSpanData], span),
                        cast(GenerationSpanData, span_data),
                    )
                elif span_type == "handoff":
                    self._process_handoff_span(
                        otel_span,
                        cast(AgentSpan[HandoffSpanData], span),
                        cast(HandoffSpanData, span_data),
                    )

                # Keep raw span data for debugging
                otel_span.set_attribute(
                    "openai_agents.span_data", json.dumps(span_data.export())
                )
                # Propagate gen_ai context from OTel baggage
                self._apply_baggage_context(otel_span)
                # Propagate conversation ID from trace to child span
                conv_id = self._conversation_ids.get(span.trace_id)
                if conv_id and not baggage.get_baggage(
                    "gen_ai.conversation.id"
                ):
                    otel_span.set_attribute("gen_ai.conversation.id", conv_id)
                end_time = self._advanced.ns_timestamp_generator()
                otel_span.end(end_time=end_time)

    def _process_agent_span(
        self,
        otel_span: otel_trace.Span,
        span: AgentSpan[AgentSpanData],
        span_data: AgentSpanData,
    ) -> None:
        """Extract attributes from agent spans.

        Sets ``gen_ai.agent.name``, ``gen_ai.tool.definitions``,
        ``gen_ai.agent.handoffs``, and ``gen_ai.agent.output_type``.

        Args:
            otel_span: The OTel span to set attributes on.
            span: The OpenAI agent span wrapper.
            span_data: The agent-specific span data.
        """
        otel_span.set_attribute("openinference.span.kind", "AGENT")
        otel_span.set_attribute("gen_ai.system", "openai")
        otel_span.set_attribute("gen_ai.provider.name", "openai")
        otel_span.set_attribute("gen_ai.agent.name", span_data.name)

        if span_data.tools:
            # span_data.tools is a list of tool name strings; wrap each as
            # {"name": ...} so ClickHouse can CAST to Array(JSON)
            otel_span.set_attribute(
                "gen_ai.tool.definitions",
                json.dumps([{"name": name} for name in span_data.tools]),
            )

        if span_data.handoffs:
            otel_span.set_attribute(
                "gen_ai.agent.handoffs", json.dumps(span_data.handoffs)
            )

        if span_data.output_type:
            otel_span.set_attribute(
                "gen_ai.agent.output_type", span_data.output_type
            )

    def _process_function_span(
        self,
        otel_span: otel_trace.Span,
        span: AgentSpan[FunctionSpanData],
        span_data: FunctionSpanData,
    ) -> None:
        """Extract attributes from function/tool spans.

        Sets ``gen_ai.tool.name``, ``gen_ai.tool.input``, and
        ``gen_ai.tool.output``.

        Args:
            otel_span: The OTel span to set attributes on.
            span: The OpenAI agent span wrapper.
            span_data: The function-specific span data.
        """
        otel_span.set_attribute("openinference.span.kind", "TOOL")
        otel_span.set_attribute("gen_ai.tool.name", span_data.name)

        if span_data.input:
            otel_span.set_attribute("gen_ai.tool.input", span_data.input)

        if span_data.output:
            otel_span.set_attribute(
                "gen_ai.tool.output", str(span_data.output)
            )

    def _process_response_span(
        self,
        otel_span: otel_trace.Span,
        span: AgentSpan[ResponseSpanData],
        span_data: ResponseSpanData,
    ) -> None:
        """Extract attributes from response spans.

        Sets ``gen_ai.system_instructions``, ``gen_ai.tool.definitions``,
        ``gen_ai.usage.input_tokens``, ``gen_ai.usage.output_tokens``,
        ``gen_ai.request.model``, ``gen_ai.response.id``,
        ``gen_ai.input.messages``, and ``gen_ai.output.messages``.

        Args:
            otel_span: The OTel span to set attributes on.
            span: The OpenAI agent span wrapper.
            span_data: The response-specific span data.
        """
        response = span_data.response
        if not response:
            return

        otel_span.set_attribute("openinference.span.kind", "LLM")
        otel_span.set_attribute("gen_ai.operation.name", "chat")
        otel_span.set_attribute("gen_ai.system", "openai")
        otel_span.set_attribute("gen_ai.provider.name", "openai")

        # System instructions
        if response.instructions and isinstance(response.instructions, str):
            sys_instructions = [
                SystemInstruction(content=response.instructions)
            ]
            otel_span.set_attribute(
                "gen_ai.system_instructions",
                json.dumps(
                    [s.model_dump(exclude_none=True) for s in sys_instructions]
                ),
            )

        # Tool definitions (with full details from Response object)
        if response.tools:
            tool_defs: list[ToolDefinition] = []
            for tool in response.tools:
                if isinstance(tool, FunctionTool):
                    tool_defs.append(
                        ToolDefinition(
                            name=tool.name,
                            description=tool.description or None,
                            parameters=tool.parameters or None,
                        )
                    )
                else:
                    # For non-function tools (web_search, file_search, mcp, etc.)
                    label = getattr(tool, "server_label", None)
                    name = (
                        f"mcp/{label}"
                        if tool.type == "mcp" and label
                        else tool.type
                    )
                    desc = getattr(tool, "server_description", None)
                    tool_defs.append(
                        ToolDefinition(name=name, description=desc)
                    )
            otel_span.set_attribute(
                "gen_ai.tool.definitions",
                json.dumps(
                    [t.model_dump(exclude_none=True) for t in tool_defs]
                ),
            )

        # Token usage
        if response.usage:
            if response.usage.input_tokens:
                otel_span.set_attribute(
                    "gen_ai.usage.input_tokens", response.usage.input_tokens
                )
            if response.usage.output_tokens:
                otel_span.set_attribute(
                    "gen_ai.usage.output_tokens", response.usage.output_tokens
                )

        # Model info
        if response.model:
            otel_span.set_attribute("gen_ai.request.model", response.model)
            otel_span.set_attribute("gen_ai.response.model", response.model)

        # Response ID
        if response.id:
            otel_span.set_attribute("gen_ai.response.id", response.id)

        # Input messages — pass typed input directly (no cast needed)
        if span_data.input:
            input_messages, _ = convert_responses_inputs_to_semconv(
                span_data.input,
                None,
            )
            if input_messages:
                otel_span.set_attribute(
                    "gen_ai.input.messages",
                    json.dumps(
                        [
                            m.model_dump(exclude_none=True)
                            for m in input_messages
                        ]
                    ),
                )

        # Output messages — pass typed output directly (no model_dump needed)
        if response.output:
            output_messages = convert_responses_outputs_to_semconv(
                response.output
            )
            if output_messages:
                otel_span.set_attribute(
                    "gen_ai.output.messages",
                    json.dumps(
                        [
                            m.model_dump(exclude_none=True)
                            for m in output_messages
                        ]
                    ),
                )

    def _process_generation_span(
        self,
        otel_span: otel_trace.Span,
        span: AgentSpan[GenerationSpanData],
        span_data: GenerationSpanData,
    ) -> None:
        """Extract attributes from generation spans.

        Sets ``gen_ai.request.model``, ``gen_ai.usage.input_tokens``,
        ``gen_ai.usage.output_tokens``, ``gen_ai.input.messages``, and
        ``gen_ai.output.messages``.

        Args:
            otel_span: The OTel span to set attributes on.
            span: The OpenAI agent span wrapper.
            span_data: The generation-specific span data.
        """
        if span_data.model:
            otel_span.set_attribute("gen_ai.request.model", span_data.model)

        if span_data.usage:
            usage = span_data.usage
            if isinstance(usage, dict):
                if "input_tokens" in usage:
                    otel_span.set_attribute(
                        "gen_ai.usage.input_tokens", usage["input_tokens"]
                    )
                if "output_tokens" in usage:
                    otel_span.set_attribute(
                        "gen_ai.usage.output_tokens", usage["output_tokens"]
                    )

        if span_data.input:
            otel_span.set_attribute(
                "gen_ai.input.messages", json.dumps(list(span_data.input))
            )

        if span_data.output:
            otel_span.set_attribute(
                "gen_ai.output.messages", json.dumps(list(span_data.output))
            )

    def _process_handoff_span(
        self,
        otel_span: otel_trace.Span,
        span: AgentSpan[HandoffSpanData],
        span_data: HandoffSpanData,
    ) -> None:
        """Extract attributes from handoff spans.

        Sets ``gen_ai.handoff.from_agent`` and ``gen_ai.handoff.to_agent``.

        Args:
            otel_span: The OTel span to set attributes on.
            span: The OpenAI agent span wrapper.
            span_data: The handoff-specific span data.
        """
        if span_data.from_agent:
            otel_span.set_attribute(
                "gen_ai.handoff.from_agent", span_data.from_agent
            )
        if span_data.to_agent:
            otel_span.set_attribute(
                "gen_ai.handoff.to_agent", span_data.to_agent
            )

    def shutdown(self) -> None:
        """Shut down the underlying tracer provider and flush pending spans."""
        self._tracer_provider.shutdown()

    def force_flush(self) -> None:
        """Flush all pending spans to the exporter."""
        self._tracer_provider.force_flush()
