"""Gen AI Semantic Conventions to OpenInference converter.

Transforms span attributes from OTel GenAI semconv format (used by
ClaudeTracingProcessor) to OpenInference flattened format (understood by
Arize Phoenix).

This is the reverse of openinference.py which converts OpenInference → GenAI.

GenAI semconv stores messages as JSON strings:
    gen_ai.input.messages   = '[{"role":"user","parts":[{"type":"text","content":"Hi"}]}]'
    gen_ai.output.messages  = '[{"role":"assistant","parts":[...]}]'

OpenInference uses flattened attributes:
    llm.input_messages.0.message.role    = "user"
    llm.input_messages.0.message.content = "Hi"
"""

__all__ = [
    "convert_genai_to_openinference",
    "OpenInferenceSpanProcessor",
]

import json
import logging
from typing import Any

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from introspection_sdk.schemas.genai import (
    InputMessage,
    OutputMessage,
    TextPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.types import GenAiSemconv as GenAI
from introspection_sdk.types import OpenInferenceSemconv as OI

logger = logging.getLogger(__name__)


def _flatten_messages(
    messages: list[InputMessage] | list[OutputMessage], prefix: str
) -> dict[str, Any]:
    """Flatten gen_ai semconv messages to OpenInference format.

    Args:
        messages: List of typed message models.
        prefix: "llm.input_messages" or "llm.output_messages".

    Returns:
        Dict of flattened OpenInference attributes.
    """
    attrs: dict[str, Any] = {}

    for i, msg in enumerate(messages):
        msg_prefix = f"{prefix}.{i}.message"
        role = msg.role
        parts = msg.parts

        # Check if this is a tool response message (single tool_call_response part)
        if len(parts) == 1 and isinstance(parts[0], ToolCallResponsePart):
            p = parts[0]
            attrs[f"{msg_prefix}.role"] = "tool"
            attrs[f"{msg_prefix}.tool_call_id"] = p.id or ""
            response = p.response
            if not isinstance(response, str):
                response = json.dumps(response)
            attrs[f"{msg_prefix}.content"] = response
            continue

        attrs[f"{msg_prefix}.role"] = role

        # Collect text content and tool calls separately
        text_parts: list[str] = []
        tc_idx = 0

        for p in parts:
            if isinstance(p, TextPart):
                text_parts.append(p.content)

            elif isinstance(p, ToolCallRequestPart):
                tc_prefix = f"{msg_prefix}.tool_calls.{tc_idx}.tool_call"
                if p.id:
                    attrs[f"{tc_prefix}.id"] = p.id
                if p.name:
                    attrs[f"{tc_prefix}.function.name"] = p.name
                if p.arguments is not None:
                    arguments = p.arguments
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments)
                    attrs[f"{tc_prefix}.function.arguments"] = arguments
                tc_idx += 1

            elif isinstance(p, ToolCallResponsePart):
                # Shouldn't reach here (handled above), but just in case
                attrs[f"{msg_prefix}.tool_call_id"] = p.id or ""
                response = p.response
                if not isinstance(response, str):
                    response = json.dumps(response)
                text_parts.append(response)

        if text_parts:
            attrs[f"{msg_prefix}.content"] = "\n".join(text_parts)

    return attrs


def _parse_messages_json(
    json_str: str, *, is_output: bool = False
) -> list[InputMessage] | list[OutputMessage]:
    """Parse a JSON string of messages into typed models.

    Args:
        json_str: JSON string of message dicts.
        is_output: If True, parse as OutputMessage, else InputMessage.

    Returns:
        List of typed message models.
    """
    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, list):
        return []

    if is_output:
        return [OutputMessage.model_validate(m) for m in raw]
    return [InputMessage.model_validate(m) for m in raw]


def convert_genai_to_openinference(
    attrs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convert gen_ai semconv span attributes to OpenInference flattened format.

    Args:
        attrs: Gen_ai semconv attributes (from ClaudeTracingProcessor spans).

    Returns:
        Dict of OpenInference flattened attributes for Arize.
    """
    if not attrs:
        return {}

    oi: dict[str, Any] = {}

    # Span kind
    oi[OI.SPAN_KIND] = "LLM"

    # Model name
    model = attrs.get(GenAI.REQUEST_MODEL)
    if model:
        oi[OI.LLM_MODEL_NAME] = model

    # Token counts
    input_tokens = attrs.get(GenAI.INPUT_TOKENS)
    if input_tokens is not None:
        oi[OI.LLM_TOKEN_COUNT_PROMPT] = input_tokens
    output_tokens = attrs.get(GenAI.OUTPUT_TOKENS)
    if output_tokens is not None:
        oi[OI.LLM_TOKEN_COUNT_COMPLETION] = output_tokens

    # System instructions → prepend as system message in input
    system_messages: list[InputMessage] = []
    sys_json = attrs.get(GenAI.SYSTEM_INSTRUCTIONS)
    if isinstance(sys_json, str) and sys_json:
        try:
            instructions = json.loads(sys_json)
            text_parts = [
                p.get("content", "")
                for p in instructions
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            if text_parts:
                system_messages.append(
                    InputMessage(
                        role="system",
                        parts=[
                            TextPart(
                                type="text",
                                content="\n".join(text_parts),
                            )
                        ],
                    )
                )
        except json.JSONDecodeError:
            pass

    # Input messages
    input_msgs_json = attrs.get(GenAI.INPUT_MESSAGES)
    if isinstance(input_msgs_json, str) and input_msgs_json:
        input_messages = _parse_messages_json(input_msgs_json)
        # _parse_messages_json returns list[InputMessage] by default
        all_input: list[InputMessage] = system_messages + input_messages  # type: ignore[operator]
        oi.update(_flatten_messages(all_input, OI.LLM_INPUT_MESSAGES))
    elif system_messages:
        oi.update(_flatten_messages(system_messages, OI.LLM_INPUT_MESSAGES))

    # Output messages
    output_msgs_json = attrs.get(GenAI.OUTPUT_MESSAGES)
    if isinstance(output_msgs_json, str) and output_msgs_json:
        output_messages = _parse_messages_json(
            output_msgs_json, is_output=True
        )
        # _parse_messages_json returns list[OutputMessage] when is_output=True
        oi.update(
            _flatten_messages(
                output_messages,
                OI.LLM_OUTPUT_MESSAGES,
            )
        )

    return oi


class _OpenInferenceSpan(ReadableSpan):
    """ReadableSpan wrapper that presents OpenInference attributes."""

    def __init__(self, original: ReadableSpan, oi_attrs: dict[str, Any]):
        self._original = original
        self._oi_attrs = oi_attrs

    @property
    def attributes(self):
        return self._oi_attrs

    def get_span_context(self):
        return self._original.get_span_context()

    @property
    def dropped_attributes(self) -> int:
        return self._original.dropped_attributes

    @property
    def dropped_events(self) -> int:
        return self._original.dropped_events

    @property
    def dropped_links(self) -> int:
        return self._original.dropped_links

    @property
    def name(self) -> str:
        return self._original.name

    @property
    def context(self):
        return self._original.context

    @property
    def parent(self):
        return self._original.parent

    @property
    def resource(self):
        return self._original.resource

    @property
    def instrumentation_info(self):
        return self._original.instrumentation_info

    @property
    def instrumentation_scope(self):
        return self._original.instrumentation_scope

    @property
    def status(self):
        return self._original.status

    @property
    def start_time(self):
        return self._original.start_time

    @property
    def end_time(self):
        return self._original.end_time

    @property
    def events(self):
        return self._original.events

    @property
    def links(self):
        return self._original.links

    @property
    def kind(self):
        return self._original.kind

    def to_json(self, indent: int | None = 4):
        return self._original.to_json(indent=indent)

    def __getattr__(self, name: str):
        return getattr(self._original, name)


class OpenInferenceSpanProcessor(SpanProcessor):
    """Wraps a downstream SpanProcessor, converting gen_ai semconv → OpenInference.

    Use this to wrap an Arize/Phoenix processor so it receives spans in the
    OpenInference format it expects, while the original gen_ai semconv spans
    continue to flow to Introspection unchanged.

    Usage:
        arize_processor = BatchSpanProcessor(arize_exporter)
        oi_processor = OpenInferenceSpanProcessor(arize_processor)

        processor = ClaudeTracingProcessor(
            additional_span_processors=[oi_processor],
        )
    """

    def __init__(self, downstream: SpanProcessor):
        """Initialize with a downstream processor to forward converted spans to.

        Args:
            downstream: The OTel span processor that expects OpenInference
                attributes (e.g. an Arize/Phoenix ``BatchSpanProcessor``).
        """
        self._downstream = downstream

    def on_start(
        self, span: Span, parent_context: Context | None = None
    ) -> None:
        """Forward span start to the downstream processor.

        Args:
            span: The span that was started.
            parent_context: The parent context of the span, if any.
        """
        self._downstream.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        """Convert gen_ai attributes to OpenInference format and forward.

        Args:
            span: The completed span to convert and forward.
        """
        original_attrs = span.attributes
        if original_attrs is None:
            self._downstream.on_end(span)
            return

        oi_attrs = convert_genai_to_openinference(dict(original_attrs))
        if oi_attrs:
            converted = _OpenInferenceSpan(span, oi_attrs)
            self._downstream.on_end(converted)
        else:
            self._downstream.on_end(span)

    def shutdown(self) -> None:
        """Shut down the downstream processor."""
        self._downstream.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush the downstream processor.

        Args:
            timeout_millis: Maximum time in milliseconds to wait for the flush.

        Returns:
            ``True`` if the flush completed within the timeout.
        """
        return self._downstream.force_flush(timeout_millis)
