"""LangChain/LangGraph Callback Handler for Introspection SDK.

Hooks into LangChain's native callback system to capture LLM, tool, and chain
interactions as gen_ai.* OTel spans for the Introspection backend.

Architecture mirrors IntrospectionTracingProcessor (for OpenAI Agents SDK):
- Creates its own OTel TracerProvider with OTLP exporter
- Implements BaseCallbackHandler lifecycle hooks
- Extracts gen_ai.* attributes from LLM/tool/chain events

Usage::

    from introspection_sdk import IntrospectionCallbackHandler

    handler = IntrospectionCallbackHandler(service_name="my-app")

    # Pass to any LangChain invoke call
    response = model.invoke("Hello!", config={"callbacks": [handler]})

    # Or set globally
    from langchain_core.callbacks import set_global_handler
    set_global_handler(handler)
"""

from __future__ import annotations

__all__ = ["IntrospectionCallbackHandler"]

import json
import os
import uuid as uuid_mod
from collections.abc import Sequence
from typing import Any, Literal, TypedDict

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
from introspection_sdk.otel._termination import (
    CANCELLATION_EXCEPTIONS,
    mark_span_cancelled,
)
from introspection_sdk.otel._usage import set_usage_cost_attributes
from introspection_sdk.schemas.genai import (
    InputMessage,
    MessagePart,
    OutputMessage,
    SystemInstruction,
    TextPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.utils import logger
from introspection_sdk.version import VERSION

# LangChain types (optional dependency)
HAS_LANGCHAIN = True
try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        ToolCall,
        ToolMessage,
    )
    from langchain_core.outputs import ChatGeneration, LLMResult
except ImportError:
    HAS_LANGCHAIN = False
    BaseCallbackHandler = object  # type: ignore[assignment,misc]


class _ToolCallDict(TypedDict, total=False):
    """Mirrors the shape of LangChain's ToolCall TypedDict."""

    id: str
    name: str
    args: dict[str, Any] | str


class _ToolDefinitionFunctionDict(TypedDict, total=False):
    """Function sub-dict inside an OpenAI-style tool definition."""

    name: str
    description: str
    parameters: dict[str, Any]


class _ToolDefinitionDict(TypedDict, total=False):
    """OpenAI-style tool definition dict from invocation_params."""

    type: str
    function: _ToolDefinitionFunctionDict


class IntrospectionCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that captures LLM, tool, and chain events
    as gen_ai.* OTel spans and exports them to the Introspection backend.

    Pass as a callback to any LangChain invoke call, or set globally.

    Args:
        token: Introspection API token. Falls back to ``INTROSPECTION_TOKEN``.
        service_name: OTel service name. Falls back to ``INTROSPECTION_SERVICE_NAME``.
        base_url: Introspection base URL. Falls back to ``INTROSPECTION_BASE_OTEL_URL``.
        advanced: Testing/customization options.
    """

    name: str = "IntrospectionCallbackHandler"

    def __init__(
        self,
        *,
        token: str | None = None,
        service_name: str | None = None,
        base_url: str | None = None,
        advanced: AdvancedOptions | None = None,
        tracer_provider: TracerProvider | None = None,
    ) -> None:
        if not HAS_LANGCHAIN:
            raise ImportError(
                "langchain-core is required for IntrospectionCallbackHandler. "
                "Install with: pip install langchain-core"
            )

        super().__init__()

        self._advanced = advanced or AdvancedOptions()

        self._owns_provider = tracer_provider is None
        if tracer_provider is not None:
            self._provider = tracer_provider
        else:
            self._provider = self._build_standalone_provider(
                token, service_name, base_url
            )

        self._tracer = self._provider.get_tracer("langchain", VERSION)
        self._spans: dict[str, otel_trace.Span] = {}
        self._span_names: dict[str, str] = {}
        self._span_parents: dict[str, str] = {}  # runId -> parentRunId
        self._run_roots: dict[str, str] = {}  # runId -> rootRunId
        self._conversation_id = f"intro_conv_{uuid_mod.uuid4().hex}"
        # Wrapper names skipped when resolving the real agent/node name.
        self._wrapper_names: frozenset[str] = frozenset(
            {
                "RunnableSequence",
                "RunnableParallel",
                "RunnableMap",
                "RunnableLambda",
                "RunnableRetry",
                "_ConfigurableModel",
                "ChatOpenAI",
                "ChatAnthropic",
                "ChatGoogleGenerativeAI",
                "ChatGroq",
            }
        )
        self._llm_inputs: dict[str, list[InputMessage]] = {}

    def _build_standalone_provider(
        self,
        token: str | None,
        service_name: str | None,
        base_url: str | None,
    ) -> TracerProvider:
        resolved_token = token or os.environ.get("INTROSPECTION_TOKEN", "")
        resolved_service = (
            service_name or os.environ.get("INTROSPECTION_SERVICE_NAME") or ""
        )
        resolved_base = (
            base_url
            or os.environ.get("INTROSPECTION_BASE_OTEL_URL")
            or "https://otel.introspection.dev"
        )

        resource = (
            Resource.create({"service.name": resolved_service})
            if resolved_service
            else Resource.create()
        )

        if self._advanced.span_exporter is not None:
            processor = SimpleSpanProcessor(self._advanced.span_exporter)
            logger.info(
                "IntrospectionCallbackHandler initialized in test mode"
            )
        else:
            if not resolved_token:
                raise ValueError("INTROSPECTION_TOKEN is required")

            endpoint = (
                resolved_base
                if resolved_base.endswith("/v1/traces")
                else f"{resolved_base.rstrip('/')}/v1/traces"
            )
            logger.info(
                "IntrospectionCallbackHandler initialized: endpoint=%s",
                endpoint,
            )

            exporter = OTLPHTTPSpanExporter(
                endpoint=endpoint,
                headers={"Authorization": f"Bearer {resolved_token}"},
                compression=Compression.NoCompression,
            )
            processor = (
                SimpleSpanProcessor(exporter)
                if resolved_token.startswith(("intro_dev", "intro_staging"))
                else BatchSpanProcessor(exporter)
            )

        provider = TracerProvider(
            resource=resource,
            id_generator=self._advanced.id_generator,
        )
        provider.add_span_processor(processor)
        return provider

    def _root_run_id(
        self, run_id: Any, parent_run_id: Any | None = None
    ) -> str:
        run_key = str(run_id)
        if parent_run_id is None:
            return run_key
        parent_key = str(parent_run_id)
        return self._run_roots.get(parent_key, parent_key)

    def _set_root_conversation_id(
        self,
        conversation_id: str,
        run_id: Any,
        parent_run_id: Any | None = None,
    ) -> None:
        """Keep the top-level run span aligned with child conversation IDs."""
        root_key = self._root_run_id(run_id, parent_run_id)
        root = self._spans.get(root_key)
        if root is not None:
            root.set_attribute("gen_ai.conversation.id", conversation_id)

    def _end_root_if_complete(self, run_id: Any) -> None:
        run_key = str(run_id)
        self._run_roots.pop(run_key, None)
        self._span_names.pop(run_key, None)
        self._span_parents.pop(run_key, None)

    def _create_child_span(
        self,
        name: str,
        run_id: Any,
        parent_run_id: Any | None = None,
    ) -> otel_trace.Span:
        """Create a span under a LangChain parent when one exists.
        Sets gen_ai.agent.name to the parent span's name for hierarchy."""
        parent = self._spans.get(str(parent_run_id)) if parent_run_id else None
        root_key = self._root_run_id(run_id, parent_run_id)
        self._run_roots[str(run_id)] = root_key
        ctx = otel_trace.set_span_in_context(parent) if parent else None
        span = self._tracer.start_span(name, context=ctx)
        self._span_names[str(run_id)] = name

        # Track parent for walk-up
        if parent_run_id:
            self._span_parents[str(run_id)] = str(parent_run_id)

        # Walk up parents to find first non-wrapper name for gen_ai.agent.name
        agent_name = self._find_agent_name(parent_run_id)
        if agent_name:
            span.set_attribute("gen_ai.agent.name", agent_name)

        return span

    # -----------------------------------------------------------------
    # Chat model callbacks
    # -----------------------------------------------------------------

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        model_name = self._extract_model_name(serialized, kwargs)
        span_name = f"chat {model_name}" if model_name else "chat"

        span = self._create_child_span(span_name, run_id, parent_run_id)
        self._spans[str(run_id)] = span

        conv_id = self._get_conversation_id(metadata)
        self._set_root_conversation_id(conv_id, run_id, parent_run_id)

        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.conversation.id", conv_id)
        span.set_attribute("openinference.span.kind", "LLM")

        if model_name:
            span.set_attribute("gen_ai.request.model", model_name)

        provider = self._extract_provider(serialized)
        if provider:
            span.set_attribute("gen_ai.system", provider)

        flat_messages = messages[0] if messages else []
        input_msgs, sys_instructions = self._convert_messages(flat_messages)

        if input_msgs:
            span.set_attribute(
                "gen_ai.input.messages",
                json.dumps(
                    [m.model_dump(exclude_none=True) for m in input_msgs]
                ),
            )
            self._llm_inputs[str(run_id)] = input_msgs

        if sys_instructions:
            span.set_attribute(
                "gen_ai.system_instructions",
                json.dumps(
                    [s.model_dump(exclude_none=True) for s in sys_instructions]
                ),
            )

        invocation_params: dict[str, Any] = kwargs.get("invocation_params", {})
        tools: list[_ToolDefinitionDict] | None = invocation_params.get(
            "tools"
        )
        if tools and isinstance(tools, list):
            span.set_attribute(
                "gen_ai.tool.definitions",
                json.dumps(
                    [self._normalize_tool_definition(t) for t in tools]
                ),
            )

        if "temperature" in invocation_params:
            span.set_attribute(
                "gen_ai.request.temperature", invocation_params["temperature"]
            )

    # -----------------------------------------------------------------
    # LLM callbacks (fallback for non-chat models)
    # -----------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        model_name = self._extract_model_name(serialized, kwargs)
        span_name = f"chat {model_name}" if model_name else "llm"

        span = self._create_child_span(span_name, run_id, parent_run_id)
        self._spans[str(run_id)] = span

        conv_id = self._get_conversation_id(metadata)
        self._set_root_conversation_id(conv_id, run_id, parent_run_id)

        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.conversation.id", conv_id)
        span.set_attribute("openinference.span.kind", "LLM")

        if model_name:
            span.set_attribute("gen_ai.request.model", model_name)

        if prompts:
            input_msgs = [
                InputMessage(
                    role="user", parts=[TextPart(type="text", content=p)]
                )
                for p in prompts
            ]
            span.set_attribute(
                "gen_ai.input.messages",
                json.dumps(
                    [m.model_dump(exclude_none=True) for m in input_msgs]
                ),
            )
            self._llm_inputs[str(run_id)] = input_msgs

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(str(run_id), None)
        self._llm_inputs.pop(str(run_id), None)
        if span is None:
            return

        generations = response.generations[0] if response.generations else []
        if generations:
            parts: list[MessagePart] = []
            for gen in generations:
                if gen.text:
                    parts.append(TextPart(type="text", content=gen.text))

                if isinstance(gen, ChatGeneration) and isinstance(
                    gen.message, AIMessage
                ):
                    for tc in gen.message.tool_calls:
                        parts.append(self._tool_call_to_request_part(tc))

            if parts:
                output_msgs = [OutputMessage(role="assistant", parts=parts)]
                span.set_attribute(
                    "gen_ai.output.messages",
                    json.dumps(
                        [m.model_dump(exclude_none=True) for m in output_msgs]
                    ),
                )

        llm_output = response.llm_output or {}
        token_usage = (
            llm_output.get("token_usage")
            or llm_output.get("tokenUsage")
            or llm_output.get("usage")
            or {}
        )
        input_tokens = token_usage.get("prompt_tokens") or token_usage.get(
            "input_tokens"
        )
        output_tokens = token_usage.get(
            "completion_tokens"
        ) or token_usage.get("output_tokens")
        if isinstance(input_tokens, int):
            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        if isinstance(output_tokens, int):
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        set_usage_cost_attributes(span, token_usage)

        model = llm_output.get("model") or llm_output.get("model_name")
        if isinstance(model, str):
            span.set_attribute("gen_ai.response.model", model)

        # gen_ai.response.id — required by the server for conversation tracking.
        # Try the provider's response ID first; fall back to the LangChain run_id.
        response_id = llm_output.get("id") or llm_output.get(
            "system_fingerprint"
        )
        if not isinstance(response_id, str):
            response_id = f"langchain-{run_id}"
        span.set_attribute("gen_ai.response.id", response_id)

        span.end()
        self._end_root_if_complete(run_id)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(str(run_id), None)
        self._llm_inputs.pop(str(run_id), None)
        if span is None:
            return
        if isinstance(error, CANCELLATION_EXCEPTIONS):
            mark_span_cancelled(span)
        else:
            span.record_exception(error)
            span.set_status(
                otel_trace.Status(otel_trace.StatusCode.ERROR, str(error))
            )
            span.set_attribute("exception.message", str(error))
        span.end()
        self._end_root_if_complete(run_id)

    # -----------------------------------------------------------------
    # Chain callbacks
    # -----------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = (
            kwargs.get("name")
            or serialized.get("name")
            or (serialized.get("id", [""]))[-1]
            or "chain"
        )

        span = self._create_child_span(name, run_id, parent_run_id)
        self._spans[str(run_id)] = span

        conv_id = self._get_conversation_id(metadata)
        self._set_root_conversation_id(conv_id, run_id, parent_run_id)
        span.set_attribute("gen_ai.conversation.id", conv_id)

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(str(run_id), None)
        if span is None:
            return
        span.end()
        self._end_root_if_complete(run_id)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(str(run_id), None)
        if span is None:
            return
        if isinstance(error, CANCELLATION_EXCEPTIONS):
            mark_span_cancelled(span)
        else:
            span.record_exception(error)
            span.set_status(
                otel_trace.Status(otel_trace.StatusCode.ERROR, str(error))
            )
            span.set_attribute("exception.message", str(error))
        span.end()
        self._end_root_if_complete(run_id)

    # -----------------------------------------------------------------
    # Tool callbacks
    # -----------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Any | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = (
            kwargs.get("name")
            or serialized.get("name")
            or (serialized.get("id", [""]))[-1]
            or "tool"
        )

        span = self._create_child_span(tool_name, run_id, parent_run_id)
        self._spans[str(run_id)] = span

        conv_id = self._get_conversation_id(metadata)
        self._set_root_conversation_id(conv_id, run_id, parent_run_id)

        span.set_attribute("gen_ai.tool.name", tool_name)
        span.set_attribute("openinference.span.kind", "TOOL")
        span.set_attribute("gen_ai.tool.input", input_str)
        span.set_attribute("gen_ai.conversation.id", conv_id)

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(str(run_id), None)
        if span is None:
            return

        if output is not None:
            out_str = (
                output
                if isinstance(output, str)
                else getattr(output, "content", None) or str(output)
            )
            span.set_attribute(
                "gen_ai.tool.output",
                out_str if isinstance(out_str, str) else json.dumps(out_str),
            )

        span.end()
        self._end_root_if_complete(run_id)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        span = self._spans.pop(str(run_id), None)
        if span is None:
            return
        if isinstance(error, CANCELLATION_EXCEPTIONS):
            mark_span_cancelled(span)
        else:
            span.record_exception(error)
            span.set_status(
                otel_trace.Status(otel_trace.StatusCode.ERROR, str(error))
            )
            span.set_attribute("exception.message", str(error))
        span.end()
        self._end_root_if_complete(run_id)

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def shutdown(self) -> None:
        """Shut down the tracer provider, flushing pending spans."""
        for span in self._spans.values():
            span.end()
        self._spans.clear()
        self._span_names.clear()
        self._span_parents.clear()
        self._run_roots.clear()
        if self._owns_provider:
            self._provider.shutdown()

    def force_flush(self) -> None:
        """Force-flush buffered spans, unless a shared provider was passed in."""
        if self._owns_provider:
            self._provider.force_flush()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _extract_model_name(
        self, serialized: dict[str, Any], kwargs: dict[str, Any]
    ) -> str | None:
        inv = kwargs.get("invocation_params", {})
        for key in ("model", "model_name", "modelName"):
            if key in inv and isinstance(inv[key], str):
                return inv[key]

        ser_kwargs = serialized.get("kwargs", {})
        for key in ("model", "model_name", "modelName"):
            if key in ser_kwargs and isinstance(ser_kwargs[key], str):
                return ser_kwargs[key]

        return None

    def _extract_provider(self, serialized: dict[str, Any]) -> str | None:
        ids = serialized.get("id", [])
        if ids:
            return ids[-1]
        return None

    def _find_agent_name(self, run_id: Any | None) -> str | None:
        """Walk up the span tree to find the first non-wrapper span name."""
        current = str(run_id) if run_id else None
        for _ in range(20):  # safety limit
            if current is None:
                return None
            name = self._span_names.get(current)
            if name and name not in self._wrapper_names:
                return name
            current = self._span_parents.get(current)
        return None

    def _get_conversation_id(
        self, metadata: dict[str, Any] | None = None
    ) -> str:
        if metadata and "gen_ai.conversation.id" in metadata:
            return str(metadata["gen_ai.conversation.id"])
        if metadata and "thread_id" in metadata:
            return str(metadata["thread_id"])
        return self._conversation_id

    def _convert_messages(
        self, messages: Sequence[BaseMessage]
    ) -> tuple[list[InputMessage], list[SystemInstruction]]:
        input_msgs: list[InputMessage] = []
        sys_instructions: list[SystemInstruction] = []

        for msg in messages:
            role = self._map_role(msg.type)
            content = msg.content

            if role == "system":
                text = content if isinstance(content, str) else str(content)
                sys_instructions.append(
                    SystemInstruction(type="text", content=text)
                )
                continue

            parts: list[MessagePart] = []

            if isinstance(msg, ToolMessage):
                tool_call_id = msg.tool_call_id
                result_text = (
                    content if isinstance(content, str) else str(content)
                )
                parts.append(
                    ToolCallResponsePart(
                        type="tool_call_response",
                        id=tool_call_id,
                        response=result_text,
                    )
                )
            elif isinstance(content, str) and content:
                parts.append(TextPart(type="text", content=content))
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(
                            TextPart(type="text", content=part.get("text", ""))
                        )

            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append(self._tool_call_to_request_part(tc))

            if parts:
                input_msgs.append(InputMessage(role=role, parts=parts))

        return input_msgs, sys_instructions

    @staticmethod
    def _tool_call_to_request_part(
        tc: ToolCall | _ToolCallDict,
    ) -> ToolCallRequestPart:
        """Convert a LangChain ToolCall dict to a ToolCallRequestPart."""
        args = tc.get("args", {})
        return ToolCallRequestPart(
            type="tool_call",
            name=tc.get("name", ""),
            id=tc.get("id", ""),
            arguments=args if isinstance(args, str) else json.dumps(args),
        )

    @staticmethod
    def _normalize_tool_definition(
        t: _ToolDefinitionDict,
    ) -> dict[str, Any]:
        """Normalize an OpenAI-style tool definition dict."""
        func: Any = t.get("function") or t
        return {
            "type": t.get("type", "function"),
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": func.get("parameters"),
        }

    @staticmethod
    def _map_role(
        msg_type: str,
    ) -> Literal["system", "user", "assistant", "tool"]:
        mapping: dict[str, Literal["system", "user", "assistant", "tool"]] = {
            "human": "user",
            "ai": "assistant",
            "system": "system",
            "tool": "tool",
        }
        return mapping.get(msg_type, "user")
