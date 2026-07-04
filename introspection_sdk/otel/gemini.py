"""Lightweight Gemini instrumentor for Introspection SDK.

Captures the full Gemini response including thought signatures
(``thought_signature`` on ``Part``), which third-party instrumentors drop.
Thought signatures are encrypted reasoning tokens that Gemini 3.x
returns alongside text and function-call parts; they must be replayed
verbatim on subsequent turns to preserve the model's reasoning state.

Both thought-text parts (``Part.thought=True``) and bare signatures
attached to function calls or other parts are captured as
:class:`~introspection_sdk.schemas.genai.ThinkingPart` entries. Bare
signatures use :data:`REDACTED_THINKING_CONTENT` (``"[redacted]"``) as
content, matching the convention used for Anthropic's
``redacted_thinking`` blocks.

Supports both non-streaming (``client.models.generate_content``) and
streaming (``client.models.generate_content_stream``) calls, plus their
async equivalents on ``client.aio.models``.

Usage — auto-instrumentor::

    from introspection_sdk.otel.gemini import GeminiInstrumentor

    instrumentor = GeminiInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    # All client.models.generate_content / stream calls are now traced

Usage — manual wrapper::

    from introspection_sdk.otel.gemini import traced_generate_content

    response = traced_generate_content(
        tracer, client, model="gemini-3.5-flash", contents="..."
    )
"""

from __future__ import annotations

__all__ = [
    "GeminiInstrumentor",
    "REDACTED_THINKING_CONTENT",
    "traced_generate_content",
]

import base64
import json
from typing import Any, Literal

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, SpanKind, StatusCode

from introspection_sdk.otel._termination import (
    CANCELLATION_EXCEPTIONS,
    mark_span_cancelled,
)
from introspection_sdk.otel._usage import (
    set_usage_cost_attributes,
    usage_cost_attributes,
)
from introspection_sdk.otel.anthropic import REDACTED_THINKING_CONTENT
from introspection_sdk.schemas.genai import (
    InputMessage,
    MessagePart,
    OutputMessage,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)

PROVIDER_NAME = "gemini"


# Gemini FinishReason enum names → gen_ai semconv finish_reason strings.
_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "max_tokens",
    "SAFETY": "safety",
    "RECITATION": "recitation",
    "LANGUAGE": "language",
    "OTHER": "other",
    "BLOCKLIST": "blocklist",
    "PROHIBITED_CONTENT": "prohibited_content",
    "SPII": "spii",
    "MALFORMED_FUNCTION_CALL": "malformed_function_call",
}


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from ``obj`` whether it's a dict or an SDK object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _encode_signature(sig: Any) -> str | None:
    """Encode a thought_signature to a JSON-safe string.

    Gemini returns signatures as ``bytes``; the wire format encodes them
    as base64. Normalize both forms to a base64 string.
    """
    if sig is None:
        return None
    if isinstance(sig, bytes):
        return base64.b64encode(sig).decode("ascii")
    if isinstance(sig, str):
        return sig
    return None


def _part_to_parts(part: Any) -> list[MessagePart]:
    """Convert a single Gemini ``Part`` (SDK object or dict) to gen_ai parts.

    Handles text, thought (with optional signature), bare thought signatures
    attached to other parts (emitted as redacted thinking), function calls,
    and function responses.
    """
    text = _get(part, "text")
    thought = bool(_get(part, "thought", False))
    signature = _encode_signature(_get(part, "thought_signature"))
    function_call = _get(part, "function_call")
    function_response = _get(part, "function_response")

    result: list[MessagePart] = []

    if thought:
        result.append(
            ThinkingPart(
                type="thinking",
                content=text if text else REDACTED_THINKING_CONTENT,
                signature=signature,
                provider_name=PROVIDER_NAME,
            )
        )
    elif signature:
        # Bare signature on a non-thought part (e.g. function_call). Emit a
        # redacted thinking part so we can replay the signature on the next
        # turn, mirroring how Anthropic ``redacted_thinking`` is captured.
        result.append(
            ThinkingPart(
                type="thinking",
                content=REDACTED_THINKING_CONTENT,
                signature=signature,
                provider_name=PROVIDER_NAME,
            )
        )

    if text and not thought:
        result.append(TextPart(type="text", content=text))

    if function_call:
        result.append(
            ToolCallRequestPart(
                type="tool_call",
                id=_get(function_call, "id") or "",
                name=_get(function_call, "name") or "",
                arguments=_get(function_call, "args"),
            )
        )

    if function_response:
        raw = _get(function_response, "response")
        if raw is None:
            resp_str = ""
        elif isinstance(raw, str):
            resp_str = raw
        else:
            try:
                resp_str = json.dumps(raw)
            except (TypeError, ValueError):
                resp_str = str(raw)
        result.append(
            ToolCallResponsePart(
                type="tool_call_response",
                id=_get(function_response, "id") or "",
                response=resp_str,
            )
        )

    return result


def _content_to_parts(content: Any) -> list[MessagePart]:
    """Convert a Gemini ``Content`` (with ``.parts``) to gen_ai parts."""
    parts = _get(content, "parts") or []
    result: list[MessagePart] = []
    for p in parts:
        result.extend(_part_to_parts(p))
    return result


def _normalize_role(
    role: str | None,
) -> Literal["system", "user", "assistant", "tool"]:
    """Map a Gemini role to a gen_ai semconv role."""
    if role in ("model", "assistant"):
        return "assistant"
    if role in ("tool", "function"):
        return "tool"
    if role == "system":
        return "system"
    return "user"


def _convert_gemini_input(contents: Any) -> list[InputMessage]:
    """Convert Gemini ``contents`` (str, Content, or list) to input messages."""
    if contents is None:
        return []
    if isinstance(contents, str):
        return [
            InputMessage(
                role="user", parts=[TextPart(type="text", content=contents)]
            )
        ]
    if not isinstance(contents, list):
        contents = [contents]

    result: list[InputMessage] = []
    for c in contents:
        if isinstance(c, str):
            result.append(
                InputMessage(
                    role="user", parts=[TextPart(type="text", content=c)]
                )
            )
            continue
        role = _normalize_role(_get(c, "role"))
        parts = _content_to_parts(c)
        if parts:
            result.append(InputMessage(role=role, parts=parts))
    return result


def _finish_reason(raw: Any) -> str:
    """Map a Gemini ``FinishReason`` to a gen_ai semconv string.

    Defaults to ``"stop"`` when missing.
    """
    if raw is None:
        return "stop"
    name = getattr(raw, "name", None) or str(raw)
    return _FINISH_REASON_MAP.get(name, name.lower())


def _convert_gemini_output(response: Any) -> list[OutputMessage]:
    """Convert Gemini response candidates to gen_ai output messages."""
    result: list[OutputMessage] = []
    for cand in _get(response, "candidates") or []:
        content = _get(cand, "content")
        parts = _content_to_parts(content) if content is not None else []
        if not parts:
            continue
        has_tool = any(isinstance(p, ToolCallRequestPart) for p in parts)
        result.append(
            OutputMessage(
                role="assistant",
                parts=parts,
                finish_reason=(
                    "tool-calls"
                    if has_tool
                    else _finish_reason(_get(cand, "finish_reason"))
                ),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


def _set_request_attrs(span: Span, kwargs: dict[str, Any]) -> None:
    """Set gen_ai request attributes on a span from generate_content kwargs."""
    input_msgs = _convert_gemini_input(kwargs.get("contents"))
    if input_msgs:
        span.set_attribute(
            "gen_ai.input.messages",
            json.dumps([m.model_dump(exclude_none=True) for m in input_msgs]),
        )

    config = kwargs.get("config")
    if config is None:
        return

    sys_instr = _get(config, "system_instruction")
    if sys_instr:
        if isinstance(sys_instr, str):
            sys_val: list[dict[str, Any]] = [
                {"type": "text", "content": sys_instr}
            ]
        elif isinstance(sys_instr, list):
            sys_val = [
                {
                    "type": "text",
                    "content": s if isinstance(s, str) else str(s),
                }
                for s in sys_instr
            ]
        else:
            # Could be a Content/Part — pull text out if possible
            text = _get(sys_instr, "text")
            sys_val = [{"type": "text", "content": text or str(sys_instr)}]
        span.set_attribute("gen_ai.system_instructions", json.dumps(sys_val))

    tools = _get(config, "tools")
    if tools:
        defs: list[dict[str, Any]] = []
        for t in tools:
            func_decls = _get(t, "function_declarations") or []
            for d in func_decls:
                defs.append(
                    {
                        "name": _get(d, "name") or "",
                        "description": _get(d, "description"),
                        "parameters": _to_jsonable(_get(d, "parameters")),
                    }
                )
        if defs:
            span.set_attribute("gen_ai.tool.definitions", json.dumps(defs))


def _to_jsonable(value: Any) -> Any:
    """JSON-serializable form of an SDK pydantic model or passthrough value."""
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True, mode="json")
    return value


def _set_response_attrs(span: Span, response: Any) -> None:
    """Set gen_ai response attributes on a span from a Gemini response."""
    output_msgs = _convert_gemini_output(response)
    if output_msgs:
        span.set_attribute(
            "gen_ai.output.messages",
            json.dumps([m.model_dump(exclude_none=True) for m in output_msgs]),
        )

    response_id = _get(response, "response_id")
    if response_id:
        span.set_attribute("gen_ai.response.id", response_id)

    model_version = _get(response, "model_version")
    if model_version:
        span.set_attribute("gen_ai.response.model", model_version)

    usage = _get(response, "usage_metadata")
    if usage:
        pt = _get(usage, "prompt_token_count")
        if pt:
            span.set_attribute("gen_ai.usage.input_tokens", pt)
        ct = _get(usage, "candidates_token_count") or 0
        tt = _get(usage, "thoughts_token_count") or 0
        total_out = ct + tt
        if total_out:
            span.set_attribute("gen_ai.usage.output_tokens", total_out)
        set_usage_cost_attributes(span, usage)

    span.set_status(StatusCode.OK)


def _start_span(tracer: trace.Tracer, model: str) -> tuple[Span, object]:
    """Create a gen_ai span and attach context. Returns (span, context_token)."""
    span = tracer.start_span(
        "chat",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.system": "gemini",
            "gen_ai.provider.name": "gemini",
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


def traced_generate_content(
    tracer: trace.Tracer,
    client: Any,
    **kwargs: Any,
) -> Any:
    """Traced wrapper around ``client.models.generate_content(**kwargs)``.

    Creates a gen_ai span with the full Gemini response including any
    thought signatures.
    """
    span, tok = _start_span(tracer, kwargs.get("model", "unknown"))
    try:
        _set_request_attrs(span, kwargs)
        response = client.models.generate_content(**kwargs)
        _set_response_attrs(span, response)
        return response
    except CANCELLATION_EXCEPTIONS:
        mark_span_cancelled(span)
        raise
    except Exception as e:
        span.set_status(StatusCode.ERROR, str(e))
        raise
    finally:
        otel_context.detach(tok)
        span.end()


# ---------------------------------------------------------------------------
# Streaming accumulators
# ---------------------------------------------------------------------------


class _StreamAccumulator:
    """Accumulates streamed chunks and writes response attrs on completion."""

    def __init__(self, span: Span, ctx_token: object) -> None:
        self._span = span
        self._ctx_token = ctx_token
        self._finalized = False
        self._candidates_parts: dict[int, list[Any]] = {}
        self._response_id: str | None = None
        self._response_model: str | None = None
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._cost_attrs: dict[str, float | int] = {}
        self._finish_reason: str | None = None

    def _process_chunk(self, chunk: Any) -> None:
        rid = _get(chunk, "response_id")
        if rid and not self._response_id:
            self._response_id = rid
        mv = _get(chunk, "model_version")
        if mv:
            self._response_model = mv
        usage = _get(chunk, "usage_metadata")
        if usage:
            pt = _get(usage, "prompt_token_count")
            if pt:
                self._input_tokens = pt
            ct = _get(usage, "candidates_token_count") or 0
            tt = _get(usage, "thoughts_token_count") or 0
            total_out = ct + tt
            if total_out:
                self._output_tokens = total_out
            self._cost_attrs.update(usage_cost_attributes(usage))
        for cand in _get(chunk, "candidates") or []:
            idx = _get(cand, "index", 0) or 0
            content = _get(cand, "content")
            if content is not None:
                parts = _get(content, "parts") or []
                self._candidates_parts.setdefault(idx, []).extend(parts)
            fr = _get(cand, "finish_reason")
            if fr is not None:
                self._finish_reason = (
                    getattr(fr, "name", None) or str(fr) or None
                )

    def _finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True

        output_msgs: list[OutputMessage] = []
        for idx in sorted(self._candidates_parts):
            parts: list[MessagePart] = []
            for p in self._candidates_parts[idx]:
                parts.extend(_part_to_parts(p))
            if not parts:
                continue
            has_tool = any(isinstance(p, ToolCallRequestPart) for p in parts)
            if has_tool:
                fr: str | None = "tool-calls"
            elif self._finish_reason:
                fr = _FINISH_REASON_MAP.get(
                    self._finish_reason, self._finish_reason.lower()
                )
            else:
                fr = "stop"
            output_msgs.append(
                OutputMessage(role="assistant", parts=parts, finish_reason=fr)
            )

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
        for key, value in self._cost_attrs.items():
            self._span.set_attribute(key, value)
        self._span.set_status(StatusCode.OK)
        otel_context.detach(self._ctx_token)  # type: ignore[arg-type]
        self._span.end()

    def _finalize_cancelled(self) -> None:
        """Terminal path when the caller aborted mid-stream: annotate the span
        as cancelled (Unset), don't set OK."""
        if self._finalized:
            return
        self._finalized = True
        mark_span_cancelled(self._span)
        otel_context.detach(self._ctx_token)  # type: ignore[arg-type]
        self._span.end()


class _SyncStreamWrapper(_StreamAccumulator):
    """Wraps a sync ``generate_content_stream`` iterator."""

    def __init__(self, inner: Any, span: Span, ctx_token: object) -> None:
        super().__init__(span, ctx_token)
        self._inner = inner

    def __iter__(self) -> Any:
        try:
            for chunk in self._inner:
                self._process_chunk(chunk)
                yield chunk
        except CANCELLATION_EXCEPTIONS:
            # Caller aborted (task cancel / Ctrl-C / early break closes the
            # generator): annotate as cancelled, not OK. ``_finalize`` in the
            # ``finally`` then no-ops because we've flipped ``_finalized``.
            self._finalize_cancelled()
            raise
        finally:
            self._finalize()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _AsyncStreamWrapper(_StreamAccumulator):
    """Wraps an async ``generate_content_stream`` async iterator."""

    def __init__(self, inner: Any, span: Span, ctx_token: object) -> None:
        super().__init__(span, ctx_token)
        self._inner = inner

    def __aiter__(self) -> Any:
        return self._aiter()

    async def _aiter(self) -> Any:
        try:
            async for chunk in self._inner:
                self._process_chunk(chunk)
                yield chunk
        except CANCELLATION_EXCEPTIONS:
            # Caller aborted (task cancel / Ctrl-C / early break closes the
            # generator): annotate as cancelled, not OK. ``_finalize`` in the
            # ``finally`` then no-ops because we've flipped ``_finalized``.
            self._finalize_cancelled()
            raise
        finally:
            self._finalize()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# Auto-instrumentor
# ---------------------------------------------------------------------------


class GeminiInstrumentor:
    """Patches ``google.genai`` ``Models`` (sync) and ``AsyncModels`` (async).

    Captures all content parts including thought signatures, mapping them
    to gen_ai semconv :class:`ThinkingPart` entries. Bare signatures
    attached to function-call parts are emitted as redacted thinking
    parts (``content="[redacted]"``), mirroring Anthropic's
    ``redacted_thinking`` handling.
    """

    _original_sync_generate: Any = None
    _original_sync_stream: Any = None
    _original_async_generate: Any = None
    _original_async_stream: Any = None
    _tracer: trace.Tracer | None = None

    def instrument(
        self, tracer_provider: TracerProvider | None = None
    ) -> None:
        """Patch ``google.genai`` ``Models`` and ``AsyncModels`` methods."""
        try:
            from google.genai import models as genai_models
        except ImportError as e:
            raise ImportError(
                "google-genai is required. Install with: pip install google-genai"
            ) from e

        provider = tracer_provider or trace.get_tracer_provider()
        self._tracer = provider.get_tracer("introspection-gemini")
        tracer = self._tracer

        sync_cls = getattr(genai_models, "Models", None)
        if sync_cls is not None:
            self._original_sync_generate = sync_cls.generate_content
            orig_sync_gen = self._original_sync_generate

            def patched_sync_generate(self_models: Any, **kwargs: Any) -> Any:
                span, tok = _start_span(tracer, kwargs.get("model", "unknown"))
                try:
                    _set_request_attrs(span, kwargs)
                    response = orig_sync_gen(self_models, **kwargs)
                    _set_response_attrs(span, response)
                    return response
                except Exception as e:
                    span.set_status(StatusCode.ERROR, str(e))
                    raise
                finally:
                    otel_context.detach(tok)
                    span.end()

            sync_cls.generate_content = patched_sync_generate

            if hasattr(sync_cls, "generate_content_stream"):
                self._original_sync_stream = sync_cls.generate_content_stream
                orig_sync_stream = self._original_sync_stream

                def patched_sync_stream(
                    self_models: Any, **kwargs: Any
                ) -> Any:
                    span, tok = _start_span(
                        tracer, kwargs.get("model", "unknown")
                    )
                    _set_request_attrs(span, kwargs)
                    try:
                        inner = orig_sync_stream(self_models, **kwargs)
                    except Exception as e:
                        span.set_status(StatusCode.ERROR, str(e))
                        otel_context.detach(tok)  # type: ignore[arg-type]
                        span.end()
                        raise
                    return _SyncStreamWrapper(inner, span, tok)

                sync_cls.generate_content_stream = patched_sync_stream

        async_cls = getattr(genai_models, "AsyncModels", None)
        if async_cls is not None:
            self._original_async_generate = async_cls.generate_content
            orig_async_gen = self._original_async_generate

            async def patched_async_generate(
                self_models: Any, **kwargs: Any
            ) -> Any:
                span, tok = _start_span(tracer, kwargs.get("model", "unknown"))
                try:
                    _set_request_attrs(span, kwargs)
                    response = await orig_async_gen(self_models, **kwargs)
                    _set_response_attrs(span, response)
                    return response
                except Exception as e:
                    span.set_status(StatusCode.ERROR, str(e))
                    raise
                finally:
                    otel_context.detach(tok)
                    span.end()

            async_cls.generate_content = patched_async_generate

            if hasattr(async_cls, "generate_content_stream"):
                self._original_async_stream = async_cls.generate_content_stream
                orig_async_stream = self._original_async_stream

                async def patched_async_stream(
                    self_models: Any, **kwargs: Any
                ) -> Any:
                    span, tok = _start_span(
                        tracer, kwargs.get("model", "unknown")
                    )
                    _set_request_attrs(span, kwargs)
                    try:
                        inner = await orig_async_stream(self_models, **kwargs)
                    except Exception as e:
                        span.set_status(StatusCode.ERROR, str(e))
                        otel_context.detach(tok)  # type: ignore[arg-type]
                        span.end()
                        raise
                    return _AsyncStreamWrapper(inner, span, tok)

                async_cls.generate_content_stream = patched_async_stream

    def uninstrument(self) -> None:
        """Restore original methods."""
        try:
            from google.genai import models as genai_models
        except ImportError:
            self._reset()
            return

        sync_cls = getattr(genai_models, "Models", None)
        if sync_cls is not None:
            if self._original_sync_generate is not None:
                sync_cls.generate_content = self._original_sync_generate
            if self._original_sync_stream is not None:
                sync_cls.generate_content_stream = self._original_sync_stream

        async_cls = getattr(genai_models, "AsyncModels", None)
        if async_cls is not None:
            if self._original_async_generate is not None:
                async_cls.generate_content = self._original_async_generate
            if self._original_async_stream is not None:
                async_cls.generate_content_stream = self._original_async_stream

        self._reset()

    def _reset(self) -> None:
        self._original_sync_generate = None
        self._original_sync_stream = None
        self._original_async_generate = None
        self._original_async_stream = None
        self._tracer = None
