"""Lightweight Anthropic instrumentor for Introspection SDK.

Captures the full Anthropic response including thinking blocks (extended
thinking) with signatures, which third-party instrumentors drop.

Supports both non-streaming (``messages.create``) and streaming
(``messages.stream`` / ``messages.create(stream=True)``) calls.

Usage — auto-instrumentor::

    from introspection_sdk.otel.anthropic import AnthropicInstrumentor

    instrumentor = AnthropicInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    # All client.messages.create / stream calls are now traced

Usage — manual wrapper::

    from introspection_sdk.otel.anthropic import traced_messages_create

    response = traced_messages_create(tracer, client, model="claude-sonnet-4-5-20250929", ...)
"""

from __future__ import annotations

__all__ = ["AnthropicInstrumentor", "traced_messages_create"]

import json
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, SpanKind, StatusCode

from introspection_sdk.schemas.genai import (
    InputMessage,
    MessagePart,
    OutputMessage,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REDACTED_THINKING_CONTENT = "[redacted]"
"""Sentinel value for redacted thinking blocks — content was encrypted by safety systems."""

# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def _block_to_parts(block: Any) -> list[MessagePart]:
    """Convert a single Anthropic content block (SDK object or dict) to parts.

    Handles: text, thinking, tool_use, tool_result, redacted_thinking.
    """
    if isinstance(block, dict):
        bt = block.get("type", "")
    else:
        bt = getattr(block, "type", "")

    if bt == "text":
        text = (
            block.get("text", "")
            if isinstance(block, dict)
            else getattr(block, "text", "")
        )
        return [TextPart(type="text", content=text)]

    if bt == "thinking":
        thinking = (
            block.get("thinking", "")
            if isinstance(block, dict)
            else getattr(block, "thinking", "")
        ) or None
        sig = (
            block.get("signature")
            if isinstance(block, dict)
            else getattr(block, "signature", None)
        ) or None
        return [
            ThinkingPart(
                type="thinking",
                content=thinking,
                signature=sig,
                provider_name="anthropic",
            )
        ]

    if bt == "redacted_thinking":
        data = (
            block.get("data", "")
            if isinstance(block, dict)
            else getattr(block, "data", "")
        ) or None
        return [
            ThinkingPart(
                type="thinking",
                content=REDACTED_THINKING_CONTENT,
                signature=data,
                provider_name="anthropic",
            )
        ]

    if bt == "tool_use":
        if isinstance(block, dict):
            return [
                ToolCallRequestPart(
                    type="tool_call",
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input"),
                )
            ]
        return [
            ToolCallRequestPart(
                type="tool_call",
                id=getattr(block, "id", ""),
                name=getattr(block, "name", ""),
                arguments=getattr(block, "input", None),
            )
        ]

    if bt == "tool_result":
        tid = (
            block.get("tool_use_id", "")
            if isinstance(block, dict)
            else getattr(block, "tool_use_id", "")
        )
        raw = (
            block.get("content", "")
            if isinstance(block, dict)
            else getattr(block, "content", "")
        )
        resp = str(raw) if raw else ""
        return [
            ToolCallResponsePart(
                type="tool_call_response", id=tid, response=resp
            )
        ]

    return []


def _convert_anthropic_input(
    messages: list[dict[str, Any]],
) -> list[InputMessage]:
    """Convert Anthropic messages list to gen_ai input messages."""
    result: list[InputMessage] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            result.append(
                InputMessage(
                    role=role, parts=[TextPart(type="text", content=content)]
                )
            )
        elif isinstance(content, list):
            parts: list[MessagePart] = []
            for block in content:
                parts.extend(_block_to_parts(block))
            if parts:
                result.append(InputMessage(role=role, parts=parts))
    return result


def _convert_anthropic_output(content: Any) -> list[OutputMessage]:
    """Convert Anthropic response content blocks to gen_ai output messages."""
    parts: list[MessagePart] = []
    has_tool_calls = False
    for block in content:
        new_parts = _block_to_parts(block)
        for p in new_parts:
            if isinstance(p, ToolCallRequestPart):
                has_tool_calls = True
        parts.extend(new_parts)
    if not parts:
        return []
    finish_reason = "tool-calls" if has_tool_calls else "stop"
    return [
        OutputMessage(
            role="assistant", parts=parts, finish_reason=finish_reason
        )
    ]


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


def _set_request_attrs(span: Span, kwargs: dict[str, Any]) -> None:
    """Set gen_ai request attributes on a span from kwargs."""
    messages = kwargs.get("messages", [])
    input_msgs = _convert_anthropic_input(messages)
    if input_msgs:
        span.set_attribute(
            "gen_ai.input.messages",
            json.dumps([m.model_dump(exclude_none=True) for m in input_msgs]),
        )

    system = kwargs.get("system")
    if system:
        sys_val = (
            [{"type": "text", "content": system}]
            if isinstance(system, str)
            else system
        )
        span.set_attribute("gen_ai.system_instructions", json.dumps(sys_val))

    tools = kwargs.get("tools")
    if tools:
        defs = [
            {
                "name": t.get("name", ""),
                "description": t.get("description"),
                "parameters": t.get("input_schema"),
            }
            for t in tools
            if isinstance(t, dict)
        ]
        if defs:
            span.set_attribute("gen_ai.tool.definitions", json.dumps(defs))


def _set_response_attrs(span: Span, response: Any) -> None:
    """Set gen_ai response attributes on a span from an Anthropic Message."""
    output_msgs = _convert_anthropic_output(response.content)
    if output_msgs:
        span.set_attribute(
            "gen_ai.output.messages",
            json.dumps([m.model_dump(exclude_none=True) for m in output_msgs]),
        )
    span.set_attribute("gen_ai.response.id", response.id)
    span.set_attribute("gen_ai.response.model", response.model)
    if response.usage:
        span.set_attribute(
            "gen_ai.usage.input_tokens", response.usage.input_tokens
        )
        span.set_attribute(
            "gen_ai.usage.output_tokens", response.usage.output_tokens
        )
    span.set_status(StatusCode.OK)


def _start_span(tracer: trace.Tracer, model: str) -> tuple[Span, object]:
    """Create a gen_ai span and attach context. Returns (span, context_token)."""
    span = tracer.start_span(
        "chat",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.system": "anthropic",
            "gen_ai.provider.name": "anthropic",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": model,
            "openinference.span.kind": "LLM",
        },
    )
    ctx = trace.set_span_in_context(span)
    tok = otel_context.attach(ctx)
    return span, tok


# ---------------------------------------------------------------------------
# Public: manual wrapper
# ---------------------------------------------------------------------------


def traced_messages_create(
    tracer: trace.Tracer,
    client: Any,
    **kwargs: Any,
) -> Any:
    """Traced wrapper around ``client.messages.create(**kwargs)``.

    Creates a gen_ai span with full Anthropic response including thinking blocks.
    """
    span, tok = _start_span(tracer, kwargs.get("model", "unknown"))
    try:
        _set_request_attrs(span, kwargs)
        response = client.messages.create(**kwargs)
        _set_response_attrs(span, response)
        return response
    except Exception as e:
        span.set_status(StatusCode.ERROR, str(e))
        raise
    finally:
        otel_context.detach(tok)
        span.end()


# ---------------------------------------------------------------------------
# Auto-instrumentor
# ---------------------------------------------------------------------------


class AnthropicInstrumentor:
    """Patches ``anthropic.Messages.create`` and ``messages.stream`` to add tracing.

    Captures all content blocks including thinking (extended thinking) with
    signatures. Supports both non-streaming and streaming calls.
    """

    _original_create: Any = None
    _original_stream: Any = None
    _tracer: trace.Tracer | None = None

    def instrument(
        self, tracer_provider: TracerProvider | None = None
    ) -> None:
        """Patch ``anthropic.Messages.create`` and ``messages.stream``."""
        try:
            import anthropic
            import anthropic.resources
            import anthropic.resources.messages
        except ImportError as e:
            raise ImportError(
                "anthropic package is required. Install with: pip install anthropic"
            ) from e

        provider = tracer_provider or trace.get_tracer_provider()
        self._tracer = provider.get_tracer("introspection-anthropic")

        orig_create = anthropic.resources.messages.Messages.create
        self._original_create = orig_create
        tracer = self._tracer

        def patched_create(self_messages: Any, **kwargs: Any) -> Any:
            # If stream=True, delegate to streaming path
            if kwargs.get("stream"):
                return _patched_stream_via_create(
                    orig_create, tracer, self_messages, **kwargs
                )
            span, tok = _start_span(tracer, kwargs.get("model", "unknown"))
            try:
                _set_request_attrs(span, kwargs)
                response = orig_create(self_messages, **kwargs)
                _set_response_attrs(span, response)
                return response
            except Exception as e:
                span.set_status(StatusCode.ERROR, str(e))
                raise
            finally:
                otel_context.detach(tok)
                span.end()

        anthropic.resources.messages.Messages.create = patched_create  # type: ignore[assignment]

        # Patch messages.stream() if it exists
        if hasattr(anthropic.resources.messages.Messages, "stream"):
            orig_stream = anthropic.resources.messages.Messages.stream
            self._original_stream = orig_stream

            def patched_stream(self_messages: Any, **kwargs: Any) -> Any:
                return _TracedMessageStream(
                    orig_stream, tracer, self_messages, **kwargs
                )

            anthropic.resources.messages.Messages.stream = patched_stream  # type: ignore[assignment]

    def uninstrument(self) -> None:
        """Restore original methods."""
        if self._original_create is not None:
            try:
                import anthropic
                import anthropic.resources
                import anthropic.resources.messages

                anthropic.resources.messages.Messages.create = (
                    self._original_create
                )
                if self._original_stream is not None:
                    anthropic.resources.messages.Messages.stream = (
                        self._original_stream
                    )
            except ImportError:
                pass
            self._original_create = None
            self._original_stream = None
            self._tracer = None


# ---------------------------------------------------------------------------
# Streaming support
# ---------------------------------------------------------------------------


def _patched_stream_via_create(
    original_create: Any,
    tracer: trace.Tracer,
    self_messages: Any,
    **kwargs: Any,
) -> Any:
    """Handle ``messages.create(stream=True)`` — wraps the returned stream."""
    span, tok = _start_span(tracer, kwargs.get("model", "unknown"))
    _set_request_attrs(span, kwargs)
    try:
        stream = original_create(self_messages, **kwargs)
        return _StreamWrapper(stream, span, tok)
    except Exception as e:
        span.set_status(StatusCode.ERROR, str(e))
        otel_context.detach(tok)  # type: ignore[arg-type]
        span.end()
        raise


class _StreamWrapper:
    """Wraps an Anthropic streaming response to accumulate content blocks.

    Tracks content_block_start/delta/stop events to build the final list of
    content blocks (including thinking blocks), then sets gen_ai output
    attributes when the stream completes.
    """

    def __init__(self, inner: Any, span: Span, ctx_token: object) -> None:
        self._inner = inner
        self._span = span
        self._ctx_token = ctx_token
        self._finalized = False
        # Accumulated state
        self._blocks: list[dict[str, Any]] = []
        self._current_block: dict[str, Any] | None = None
        self._response_id: str | None = None
        self._response_model: str | None = None
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def __iter__(self) -> Any:
        return self

    def __next__(self) -> Any:
        try:
            event = next(self._inner)
            self._process_event(event)
            return event
        except StopIteration:
            self._finalize()
            raise

    def __enter__(self) -> Any:
        if hasattr(self._inner, "__enter__"):
            self._inner.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if hasattr(self._inner, "__exit__"):
            self._inner.__exit__(*args)
        self._finalize()

    def _process_event(self, event: Any) -> None:
        """Accumulate content from SSE events."""
        etype = getattr(event, "type", "")

        if etype == "message_start":
            msg = getattr(event, "message", None)
            if msg:
                self._response_id = getattr(msg, "id", None)
                self._response_model = getattr(msg, "model", None)
                usage = getattr(msg, "usage", None)
                if usage:
                    self._input_tokens = getattr(usage, "input_tokens", 0)

        elif etype == "content_block_start":
            cb = getattr(event, "content_block", None)
            if cb:
                bt = getattr(cb, "type", "")
                self._current_block = {"type": bt}
                if bt == "thinking":
                    self._current_block["thinking"] = ""
                    self._current_block["signature"] = ""
                elif bt == "text":
                    self._current_block["text"] = ""

        elif etype == "content_block_delta":
            delta = getattr(event, "delta", None)
            if delta and self._current_block:
                dt = getattr(delta, "type", "")
                if dt == "thinking_delta":
                    self._current_block["thinking"] += getattr(
                        delta, "thinking", ""
                    )
                elif dt == "text_delta":
                    self._current_block["text"] += getattr(delta, "text", "")
                elif dt == "signature_delta":
                    self._current_block["signature"] += getattr(
                        delta, "signature", ""
                    )
                elif dt == "input_json_delta":
                    # tool_use input accumulation
                    self._current_block.setdefault("partial_json", "")
                    self._current_block["partial_json"] += getattr(
                        delta, "partial_json", ""
                    )

        elif etype == "content_block_stop":
            if self._current_block:
                # Finalize tool_use blocks
                if (
                    self._current_block.get("type") == "tool_use"
                    and "partial_json" in self._current_block
                ):
                    import json as _json

                    try:
                        self._current_block["input"] = _json.loads(
                            self._current_block.pop("partial_json")
                        )
                    except (ValueError, KeyError):
                        self._current_block.pop("partial_json", None)
                self._blocks.append(self._current_block)
                self._current_block = None

        elif etype == "message_delta":
            delta = getattr(event, "delta", None)
            usage = getattr(event, "usage", None)
            if usage:
                self._output_tokens = getattr(usage, "output_tokens", 0)

    def _finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True

        if self._blocks:
            output_msgs = _convert_anthropic_output_from_dicts(self._blocks)
            if output_msgs:
                self._span.set_attribute(
                    "gen_ai.output.messages",
                    json.dumps(
                        [m.model_dump(exclude_none=True) for m in output_msgs]
                    ),
                )
        if self._response_id:
            self._span.set_attribute("gen_ai.response.id", self._response_id)
        if self._response_model:
            self._span.set_attribute(
                "gen_ai.response.model", self._response_model
            )
        if self._input_tokens:
            self._span.set_attribute(
                "gen_ai.usage.input_tokens", self._input_tokens
            )
        if self._output_tokens:
            self._span.set_attribute(
                "gen_ai.usage.output_tokens", self._output_tokens
            )
        self._span.set_status(StatusCode.OK)
        otel_context.detach(self._ctx_token)  # type: ignore[arg-type]
        self._span.end()

    # Proxy common stream attributes
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _convert_anthropic_output_from_dicts(
    blocks: list[dict[str, Any]],
) -> list[OutputMessage]:
    """Convert accumulated dict blocks to output messages."""
    parts: list[MessagePart] = []
    has_tool_calls = False
    for block in blocks:
        new_parts = _block_to_parts(block)
        for p in new_parts:
            if isinstance(p, ToolCallRequestPart):
                has_tool_calls = True
        parts.extend(new_parts)
    if not parts:
        return []
    finish_reason = "tool-calls" if has_tool_calls else "stop"
    return [
        OutputMessage(
            role="assistant", parts=parts, finish_reason=finish_reason
        )
    ]


class _TracedMessageStream:
    """Wraps ``messages.stream()`` context manager to add tracing."""

    def __init__(
        self,
        original_stream: Any,
        tracer: trace.Tracer,
        self_messages: Any,
        **kwargs: Any,
    ) -> None:
        self._original_stream = original_stream
        self._tracer = tracer
        self._self_messages = self_messages
        self._kwargs = kwargs
        self._span: Span | None = None
        self._ctx_token: object | None = None
        self._inner: Any = None

    def __enter__(self) -> Any:
        self._span, self._ctx_token = _start_span(
            self._tracer, self._kwargs.get("model", "unknown")
        )
        _set_request_attrs(self._span, self._kwargs)
        self._inner = self._original_stream(
            self._self_messages, **self._kwargs
        )
        ctx = self._inner.__enter__()
        return ctx

    def __exit__(self, *args: Any) -> None:
        if self._inner is not None:
            # Capture final message before closing
            msg = getattr(self._inner, "get_final_message", lambda: None)()
            if msg and self._span:
                _set_response_attrs(self._span, msg)
            self._inner.__exit__(*args)
        if self._span:
            if not self._span.is_recording():
                pass
            else:
                self._span.set_status(StatusCode.OK)
            self._span.end()
        if self._ctx_token is not None:
            otel_context.detach(self._ctx_token)  # type: ignore[arg-type]
