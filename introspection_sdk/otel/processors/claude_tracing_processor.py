"""Claude Agent SDK TracingProcessor for Introspection SDK.

Wraps ClaudeSDKClient to intercept conversations and forward traces to the
Introspection backend via OTLP with OTel Gen AI semantic convention attributes.

Architecture mirrors IntrospectionTracingProcessor (for OpenAI Agents SDK):
- Creates its own OTel TracerProvider with OTLP exporter
- Patches ClaudeSDKClient to create spans from conversation messages
- Extracts gen_ai.* attributes from StreamEvent, AssistantMessage, UserMessage, ResultMessage
"""

from __future__ import annotations

__all__ = ["ClaudeTracingProcessor"]

import inspect
import json
import os
import sys
import uuid as uuid_mod
from collections.abc import Sequence
from typing import Any
from urllib.parse import urljoin

from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as OTLPHTTPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
)

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.schemas.genai import (
    InputMessage,
    MessagePart,
    OutputMessage,
    SystemInstruction,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.utils import logger, platform_is_emscripten
from introspection_sdk.version import VERSION

try:
    import claude_agent_sdk
except ImportError:
    claude_agent_sdk = None  # type: ignore[assignment]


def _content_blocks_to_parts(
    content: Sequence[Any] | None,
) -> list[MessagePart]:
    """Convert Claude Agent SDK content blocks to gen_ai semconv parts.

    Handles both SDK objects (with attributes like .type, .text) and plain
    dicts (e.g. streaming input chunks ``{"type": "text", "text": "..."}``,
    or image blocks ``{"type": "image", "source": {...}}``).

    Args:
        content: Iterable of content blocks — SDK objects (``TextBlock``,
            ``ToolUseBlock``, ``ToolResultBlock``) or plain dicts.

    Returns:
        List of typed gen_ai semconv part models.
    """
    parts: list[MessagePart] = []
    if not content:
        return parts

    for block in content:
        # Determine block_type from dict or object
        if isinstance(block, dict):
            block_type = block.get("type")
        else:
            block_type = getattr(block, "type", None)
            if block_type is None:
                class_name = type(block).__name__
                if class_name == "TextBlock":
                    block_type = "text"
                elif class_name == "ToolUseBlock":
                    block_type = "tool_use"
                elif class_name == "ToolResultBlock":
                    block_type = "tool_result"

        if block_type == "text":
            text = (
                block.get("text", block.get("content", ""))
                if isinstance(block, dict)
                else getattr(block, "text", "")
            )
            parts.append(TextPart(type="text", content=text))

        elif block_type == "tool_use":
            if isinstance(block, dict):
                parts.append(
                    ToolCallRequestPart(
                        type="tool_call",
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input"),
                    )
                )
            else:
                parts.append(
                    ToolCallRequestPart(
                        type="tool_call",
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        arguments=getattr(block, "input", None),
                    )
                )

        elif block_type == "tool_result":
            if isinstance(block, dict):
                raw = block.get("content", "")
                tool_use_id = block.get("tool_use_id", "")
            else:
                raw = getattr(block, "content", "")
                tool_use_id = getattr(block, "tool_use_id", "")
            if isinstance(raw, list):
                texts = []
                for p in raw:
                    if isinstance(p, dict) and p.get("type") == "text":
                        texts.append(str(p.get("text", "")))
                    elif isinstance(p, str):
                        texts.append(p)
                response = " ".join(texts)
            else:
                response = str(raw) if raw else ""
            parts.append(
                ToolCallResponsePart(
                    type="tool_call_response",
                    id=tool_use_id,
                    response=response,
                )
            )

        elif block_type == "image":
            # Capture image blocks as text metadata (source type + media_type)
            if isinstance(block, dict):
                source = block.get("source", {})
            else:
                source = getattr(block, "source", {})
                if not isinstance(source, dict):
                    source = {}
            media_type = source.get(
                "media_type", source.get("type", "unknown")
            )
            parts.append(
                TextPart(type="text", content=f"[image: {media_type}]")
            )

        elif block_type == "thinking":
            # Claude thinking/reasoning blocks
            if isinstance(block, dict):
                thinking_text = block.get("thinking", "")
                signature = block.get("signature") or None
            else:
                thinking_text = getattr(block, "thinking", "")
                signature = getattr(block, "signature", None) or None
            parts.append(
                ThinkingPart(
                    type="thinking",
                    content=thinking_text or None,
                    signature=signature,
                    provider_name="anthropic",
                )
            )

    return parts


def _build_input_messages(
    prompt: Any, input_messages: list[InputMessage]
) -> None:
    """Convert a prompt (str, dict, or list) into gen_ai semconv input messages.

    Mutates *input_messages* in place.  Handles:

    - ``str``  -- plain text prompt
    - ``dict`` -- single message ``{"role": ..., "content": ...}`` or
      ``{"type": "user", "message": {"role": ..., "content": ...}}``
    - ``list`` -- captured async-generator chunks (dicts with ``"type":"text"``),
      a list of strings, or a list of message dicts

    Args:
        prompt: The user prompt in any of the formats described above.
        input_messages: Accumulator list to append converted messages to.
    """
    if isinstance(prompt, str):
        input_messages.append(
            InputMessage(
                role="user",
                parts=[TextPart(type="text", content=prompt)],
            )
        )
    elif isinstance(prompt, dict):
        msg = prompt.get("message", prompt)
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            input_messages.append(
                InputMessage(
                    role=role,
                    parts=[TextPart(type="text", content=content)],
                )
            )
        elif isinstance(content, list):
            parts = _content_blocks_to_parts(content)
            if parts:
                input_messages.append(InputMessage(role=role, parts=parts))
    elif isinstance(prompt, list):
        # Could be captured streaming chunks (list of dicts with "type":"text")
        # or a list of message dicts with role/content.
        _streaming_texts: list[str] = []
        for item in prompt:
            if isinstance(item, str):
                input_messages.append(
                    InputMessage(
                        role="user",
                        parts=[TextPart(type="text", content=item)],
                    )
                )
            elif isinstance(item, dict):
                # Streaming chunk: {"type": "text", "text": "..."}
                if "type" in item and "text" in item and "role" not in item:
                    _streaming_texts.append(str(item.get("text", "")))
                else:
                    # Message dict: {"role": ..., "content": ...}
                    msg = item.get("message", item)
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        input_messages.append(
                            InputMessage(
                                role=role,
                                parts=[TextPart(type="text", content=content)],
                            )
                        )
                    elif isinstance(content, list):
                        parts = _content_blocks_to_parts(content)
                        if parts:
                            input_messages.append(
                                InputMessage(role=role, parts=parts)
                            )
        # Combine captured streaming text chunks into a single user message
        if _streaming_texts:
            input_messages.append(
                InputMessage(
                    role="user",
                    parts=[
                        TextPart(
                            type="text",
                            content=" ".join(_streaming_texts),
                        )
                    ],
                )
            )


class ClaudeTracingProcessor:
    """Wraps ClaudeSDKClient to forward traces to Introspection backend via OTLP.

    Extracts OTel Gen AI semantic convention attributes from the conversation
    message stream:
    - StreamEvent: gen_ai.response.id (uuid), gen_ai.conversation.id (session_id),
      streaming text deltas for gen_ai.output.messages
    - AssistantMessage: gen_ai.output.messages, gen_ai.request.model
    - UserMessage: tool results added to conversation history
    - ResultMessage: gen_ai.usage.input/output_tokens, gen_ai.conversation.id

    For best tracing granularity, set ``include_partial_messages=True`` on
    ``ClaudeAgentOptions``.  This enables ``StreamEvent`` messages which carry
    a unique ``uuid`` per response (used as ``gen_ai.response.id``) and
    ``session_id`` (used as ``gen_ai.conversation.id``).  Without it, response
    IDs are generated client-side and streaming output text is not captured.

    Usage::

        processor = ClaudeTracingProcessor()
        processor.configure()

        options = ClaudeAgentOptions(
            include_partial_messages=True,  # recommended for tracing
        )
        async with ClaudeSDKClient(options=options) as client:
            await client.query("Hello")
            async for msg in client.receive_response():
                print(msg)

        processor.force_flush()
        processor.shutdown()
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        service_name: str | None = None,
        advanced: AdvancedOptions | None = None,
        additional_span_processors: list[SpanProcessor] | None = None,
        resource_attributes: dict[str, str] | None = None,
        tracer_provider: TracerProvider | None = None,
    ):
        """Initialize the Claude tracing processor.

        Args:
            token: Introspection API token. Falls back to the
                ``INTROSPECTION_TOKEN`` environment variable.
            advanced: Optional :class:`AdvancedOptions` for custom exporters,
                headers, batch settings, etc.
            additional_span_processors: Extra OTel span processors for dual
                export (e.g. Arize, Langfuse). Attached in both standalone and
                shared-provider modes.
            resource_attributes: Extra OTel resource attributes to attach to
                every span.
            tracer_provider: Shared provider to use instead of building one;
                when given, the caller owns its lifecycle.

        Raises:
            ValueError: If neither ``token`` nor ``INTROSPECTION_TOKEN`` is set
                (standalone mode only).
        """
        self._advanced = advanced or AdvancedOptions()

        self._owns_provider = tracer_provider is None
        if tracer_provider is not None:
            self._tracer_provider = tracer_provider
        else:
            self._tracer_provider = self._build_standalone_provider(
                token, service_name, resource_attributes
            )

        if additional_span_processors:
            for proc in additional_span_processors:
                self._tracer_provider.add_span_processor(proc)

        self._tracer = self._tracer_provider.get_tracer(
            "claude-agent-sdk", VERSION
        )

    def _build_standalone_provider(
        self,
        token: str | None,
        service_name: str | None,
        resource_attributes: dict[str, str] | None,
    ) -> TracerProvider:
        if self._advanced.span_exporter:
            exporter = self._advanced.span_exporter
        else:
            base_url = self._advanced.base_url or os.getenv(
                "INTROSPECTION_BASE_OTEL_URL",
                "https://otel.introspection.dev",
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
            logger.info(f"ClaudeTracingProcessor endpoint: {endpoint}")
            exporter = OTLPHTTPSpanExporter(
                endpoint=endpoint,
                compression=Compression.NoCompression,
                headers=headers,
            )

        _service_name = service_name or os.getenv(
            "INTROSPECTION_SERVICE_NAME", "claude-agent"
        )
        attrs: dict[str, str] = {"service.name": _service_name}
        if resource_attributes:
            attrs.update(resource_attributes)
        provider = TracerProvider(
            id_generator=self._advanced.id_generator,
            resource=Resource.create(attrs),
        )
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
        if platform_is_emscripten() or max_batch == 1:
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        else:
            provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    schedule_delay_millis=self._advanced.flush_interval_ms,
                    max_export_batch_size=max_batch,
                )
            )
        return provider

    def configure(self) -> None:
        """Patch ClaudeSDKClient to trace conversations.

        Can be called alongside other wrappers (e.g., LangSmith's
        configure_claude_agent_sdk). Each wrapper replaces
        ``claude_agent_sdk.ClaudeSDKClient`` with its own subclass.
        The **last** wrapper to call ``configure()`` becomes the
        outermost class in the MRO, so its ``receive_response`` runs
        first and delegates to the next via ``super()``.  Call
        ``configure()`` after any third-party wrappers so that
        Introspection sits at the top of the stack and can observe
        the full conversation (including any modifications made by
        inner wrappers).
        """
        if claude_agent_sdk is None:
            raise RuntimeError(
                "ClaudeTracingProcessor requires the `claude-agent-sdk` package.\n"
                "Install it with: pip install 'introspection-sdk[claude-agent-sdk]'"
            )

        original_class = claude_agent_sdk.ClaudeSDKClient
        processor = self

        class IntrospectionClaudeSDKClient(original_class):
            """ClaudeSDKClient subclass that creates OTel spans for Introspection."""

            async def query(self, prompt: Any = None, **kwargs: Any) -> Any:  # type: ignore[override]
                # Capture prompt for use in receive_response.
                # For async generators/iterables (streaming text input),
                # wrap them to record chunks as they flow through to the SDK.
                if prompt is not None and (
                    inspect.isasyncgen(prompt) or hasattr(prompt, "__aiter__")
                ):
                    captured: list[Any] = []

                    async def _capture_wrapper(aiter: Any):  # noqa: ANN401
                        async for chunk in aiter:
                            captured.append(chunk)
                            yield chunk

                    result = await super().query(
                        prompt=_capture_wrapper(prompt), **kwargs
                    )
                    self._intro_prompt = captured
                    return result

                self._intro_prompt = prompt
                return await super().query(prompt=prompt, **kwargs)

            async def receive_response(self):
                # Extract options — Claude SDK may use _options or options
                options = getattr(self, "_options", None) or getattr(
                    self, "options", None
                )
                model = (
                    getattr(options, "model", "unknown")
                    if options
                    else "unknown"
                )

                start_time = processor._advanced.ns_timestamp_generator()
                span = processor._tracer.start_span(
                    "claude.chat", start_time=start_time
                )
                span.set_attribute("gen_ai.system", "anthropic")
                span.set_attribute("gen_ai.operation.name", "chat")
                span.set_attribute("gen_ai.provider.name", "anthropic")
                span.set_attribute("gen_ai.request.model", model)

                # --- system_prompt vs system_instructions ----------------
                system_instructions: list[SystemInstruction] = []
                if options:
                    system_prompt = getattr(options, "system_prompt", None)
                    if system_prompt:
                        # Always persist the raw config
                        span.set_attribute(
                            "gen_ai.system_prompt",
                            json.dumps(system_prompt)
                            if not isinstance(system_prompt, str)
                            else system_prompt,
                        )

                        # Extract the instructional text portion
                        if isinstance(system_prompt, str):
                            system_instructions.append(
                                SystemInstruction(
                                    type="text", content=system_prompt
                                )
                            )
                        elif isinstance(system_prompt, dict):
                            # Preset: {"type":"preset","preset":"...","append":"..."}
                            append = system_prompt.get("append", "")
                            if append:
                                system_instructions.append(
                                    SystemInstruction(
                                        type="text", content=append
                                    )
                                )
                        elif isinstance(system_prompt, list):
                            for block in system_prompt:
                                if isinstance(block, str):
                                    system_instructions.append(
                                        SystemInstruction(
                                            type="text", content=block
                                        )
                                    )
                                elif isinstance(block, dict):
                                    text = block.get(
                                        "text", block.get("content", "")
                                    )
                                    system_instructions.append(
                                        SystemInstruction(
                                            type="text", content=str(text)
                                        )
                                    )
                        if system_instructions:
                            span.set_attribute(
                                "gen_ai.system_instructions",
                                json.dumps(
                                    [
                                        s.model_dump(exclude_none=True)
                                        for s in system_instructions
                                    ]
                                ),
                            )

                    # --- Agent definitions --------------------------------
                    agents = getattr(options, "agents", None)
                    if agents and isinstance(agents, dict):
                        agent_defs: list[dict[str, Any]] = []
                        for name, defn in agents.items():
                            agent_info: dict[str, Any] = {"name": name}
                            for field_name in (
                                "description",
                                "prompt",
                                "model",
                            ):
                                val = getattr(defn, field_name, None)
                                if val is not None:
                                    agent_info[field_name] = val
                            tools = getattr(defn, "tools", None)
                            if tools:
                                agent_info["tools"] = list(tools)
                            agent_defs.append(agent_info)
                        span.set_attribute(
                            "gen_ai.agent.definitions",
                            json.dumps(agent_defs),
                        )

                    # --- Resume / conversation ID -------------------------
                    resume_id = getattr(options, "resume", None)
                    if resume_id:
                        span.set_attribute(
                            "gen_ai.conversation.id", str(resume_id)
                        )

                # --- Build conversation history from prompt ---------------
                input_messages: list[InputMessage] = []
                prompt = getattr(self, "_intro_prompt", None)
                if prompt:
                    _build_input_messages(prompt, input_messages)

                # Accumulate all output across turns
                all_output_parts: list[MessagePart] = []
                # Track the latest StreamEvent uuid for response_id
                last_response_id: str | None = None
                # Accumulate streaming text deltas
                streaming_text_chunks: list[str] = []

                try:
                    async for msg in super().receive_response():
                        msg_type = type(msg).__name__

                        if msg_type == "StreamEvent":
                            # StreamEvent carries a per-message uuid
                            evt_uuid = getattr(msg, "uuid", None)
                            if evt_uuid:
                                last_response_id = str(evt_uuid)

                            # Capture session_id from stream events
                            evt_session = getattr(msg, "session_id", None)
                            if evt_session:
                                span.set_attribute(
                                    "gen_ai.conversation.id",
                                    str(evt_session),
                                )

                            # Accumulate text from content_block_delta
                            event = getattr(msg, "event", None)
                            if isinstance(event, dict):
                                evt_type = event.get("type")
                                if evt_type == "content_block_delta":
                                    delta = event.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        text = delta.get("text", "")
                                        if text:
                                            streaming_text_chunks.append(text)

                        elif msg_type == "AssistantMessage":
                            msg_model = getattr(msg, "model", None)
                            if msg_model:
                                span.set_attribute(
                                    "gen_ai.request.model", msg_model
                                )
                                span.set_attribute(
                                    "gen_ai.response.model", msg_model
                                )

                            content = getattr(msg, "content", [])
                            parts = _content_blocks_to_parts(content)
                            if parts:
                                all_output_parts.extend(parts)
                                input_messages.append(
                                    InputMessage(role="assistant", parts=parts)
                                )

                        elif msg_type == "UserMessage":
                            content = getattr(msg, "content", [])
                            parts = _content_blocks_to_parts(content)
                            if parts:
                                input_messages.append(
                                    InputMessage(role="user", parts=parts)
                                )

                        elif msg_type == "ResultMessage":
                            usage = getattr(msg, "usage", None)
                            if usage:
                                if isinstance(usage, dict):
                                    input_tokens = usage.get("input_tokens")
                                    output_tokens = usage.get("output_tokens")
                                else:
                                    input_tokens = getattr(
                                        usage, "input_tokens", None
                                    )
                                    output_tokens = getattr(
                                        usage, "output_tokens", None
                                    )
                                if input_tokens is not None:
                                    span.set_attribute(
                                        "gen_ai.usage.input_tokens",
                                        input_tokens,
                                    )
                                if output_tokens is not None:
                                    span.set_attribute(
                                        "gen_ai.usage.output_tokens",
                                        output_tokens,
                                    )

                            # session_id is the conversation identifier
                            session_id = getattr(msg, "session_id", None)
                            if session_id:
                                span.set_attribute(
                                    "gen_ai.conversation.id",
                                    str(session_id),
                                )

                        yield msg
                finally:
                    # Set final input messages
                    if input_messages:
                        span.set_attribute(
                            "gen_ai.input.messages",
                            json.dumps(
                                [
                                    m.model_dump(exclude_none=True)
                                    for m in input_messages
                                ]
                            ),
                        )

                    # Merge streaming deltas into output if no
                    # AssistantMessage parts were captured (pure streaming)
                    if streaming_text_chunks and not all_output_parts:
                        all_output_parts.append(
                            TextPart(
                                type="text",
                                content="".join(streaming_text_chunks),
                            )
                        )

                    if all_output_parts:
                        output_msgs = [
                            OutputMessage(
                                role="assistant", parts=all_output_parts
                            )
                        ]
                        span.set_attribute(
                            "gen_ai.output.messages",
                            json.dumps(
                                [
                                    m.model_dump(exclude_none=True)
                                    for m in output_msgs
                                ]
                            ),
                        )

                    # Use StreamEvent uuid if captured, else generate one
                    response_id = last_response_id or str(uuid_mod.uuid4())
                    span.set_attribute("gen_ai.response.id", response_id)

                    end_time = processor._advanced.ns_timestamp_generator()
                    span.end(end_time=end_time)

        # Replace the class globally
        claude_agent_sdk.ClaudeSDKClient = IntrospectionClaudeSDKClient  # type: ignore[assignment]

        # Patch any module that already imported the original class.
        # Only check modules likely to reference claude_agent_sdk,
        # not the entire sys.modules (which triggers side effects in
        # unrelated packages like scipy).
        for mod_name, module in list(sys.modules.items()):
            if module is None or module is claude_agent_sdk:
                continue
            if not (
                mod_name == "__main__"
                or "claude" in mod_name
                or "introspection" in mod_name
                or "langsmith" in mod_name
            ):
                continue
            for attr_name in dir(module):
                try:
                    if getattr(module, attr_name) is original_class:
                        setattr(
                            module,
                            attr_name,
                            IntrospectionClaudeSDKClient,
                        )
                except Exception:
                    pass

    def shutdown(self) -> None:
        """Shut down the provider, unless a shared one was passed in (caller owns it)."""
        if self._owns_provider:
            self._tracer_provider.shutdown()

    def force_flush(self) -> None:
        """Flush pending spans, unless a shared provider was passed in."""
        if self._owns_provider:
            self._tracer_provider.force_flush()
