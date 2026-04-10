"""OpenInference to GenAI Semantic Conventions converter.

Transforms span attributes from OpenInference format (used by Arize/Phoenix, Langfuse,
Braintrust when using OpenAIInstrumentor) to OTel GenAI semantic conventions.

OpenInference uses flattened attributes like:
    llm.input_messages.0.message.role
    llm.input_messages.0.message.content

This converts to GenAI semconv format:
    gen_ai.request.model
    gen_ai.input.messages (JSON string)
    gen_ai.output.messages (JSON string)
    gen_ai.tool.definitions (JSON string)
    gen_ai.system_instructions (JSON string, optional)
"""

__all__ = [
    "convert_openinference_to_genai",
    "is_openinference_span",
    "ConvertedReadableSpan",
]

import json
import logging
import re
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.util.types import Attributes

from introspection_sdk.schemas.genai import (
    InputMessage,
    MessagePart,
    OutputMessage,
    SystemInstruction,
    TextPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
    ToolDefinition,
)
from introspection_sdk.types import GenAiAttributes
from introspection_sdk.types import OpenInferenceSemconv as OI

logger = logging.getLogger(__name__)


def extract_model_name(attrs: Attributes | None) -> str | None:
    """Extract ``gen_ai.request.model`` from ``llm.model_name``.

    Args:
        attrs: OpenInference span attributes.

    Returns:
        The model name string, or ``None`` if not present.
    """
    if attrs is None:
        return None
    value = attrs.get(OI.LLM_MODEL_NAME)
    if isinstance(value, str):
        return value
    return None


def extract_system(attrs: Attributes | None) -> str | None:
    """Extract ``gen_ai.system`` from ``llm.system``.

    Args:
        attrs: OpenInference span attributes.

    Returns:
        The LLM provider system string (e.g. ``"openai"``), or ``None``.
    """
    if attrs is None:
        return None
    value = attrs.get(OI.LLM_SYSTEM)
    if isinstance(value, str):
        return value
    return None


def extract_token_usage(attrs: Attributes | None) -> dict[str, int]:
    """Extract ``gen_ai.usage.*`` from ``llm.token_count.*``.

    Per OTel GenAI semconv:
    https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/

    Args:
        attrs: OpenInference span attributes.

    Returns:
        Dict with ``"gen_ai.usage.input_tokens"`` and/or
        ``"gen_ai.usage.output_tokens"`` keys. Empty dict if unavailable.
    """
    usage = {}
    if attrs is None:
        return usage

    if OI.LLM_TOKEN_COUNT_PROMPT in attrs:
        usage["gen_ai.usage.input_tokens"] = attrs[OI.LLM_TOKEN_COUNT_PROMPT]
    if OI.LLM_TOKEN_COUNT_COMPLETION in attrs:
        usage["gen_ai.usage.output_tokens"] = attrs[
            OI.LLM_TOKEN_COUNT_COMPLETION
        ]
    if "llm.token_count.prompt_details.cache_write" in attrs:
        usage["gen_ai.usage.cache_creation.input_tokens"] = attrs[
            "llm.token_count.prompt_details.cache_write"
        ]
    if "llm.token_count.prompt_details.cache_read" in attrs:
        usage["gen_ai.usage.cache_read.input_tokens"] = attrs[
            "llm.token_count.prompt_details.cache_read"
        ]

    return usage


def _extract_response_id_from_langchain_output(
    payload: dict[str, Any],
) -> str | None:
    """Extract OpenAI response id from LangChainInstrumentor ``output.value``.

    LangChainInstrumentor encodes outputs as a ``generations`` structure where
    the OpenAI response id is nested under::

        generations[*][*].message.kwargs.response_metadata.id

    Args:
        payload: Parsed JSON dict from ``output.value``.

    Returns:
        The response id string, or ``None`` if not found.
    """
    generations = payload.get("generations")
    if not isinstance(generations, list):
        return None

    def extract_from_item(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        message = item.get("message")
        if not isinstance(message, dict):
            return None
        kwargs = message.get("kwargs")
        if not isinstance(kwargs, dict):
            return None
        response_metadata = kwargs.get("response_metadata")
        if not isinstance(response_metadata, dict):
            return None
        response_id = response_metadata.get("id")
        return (
            response_id
            if isinstance(response_id, str) and response_id
            else None
        )

    for outer in generations:
        if isinstance(outer, list):
            for item in outer:
                response_id = extract_from_item(item)
                if response_id:
                    return response_id
        else:
            response_id = extract_from_item(outer)
            if response_id:
                return response_id

    return None


def extract_response_id(attrs: Attributes | None) -> str | None:
    """Extract ``gen_ai.response.id`` from OpenInference attributes.

    OpenInference OpenAI spans include ``output.value`` as a JSON string.

    Known formats (from fixtures):

    - Chat Completions: ``output.value`` JSON has ``object="chat.completion"``
      and top-level ``id="chatcmpl-..."``.
    - Responses API: ``output.value`` JSON has ``object="response"`` and
      top-level ``id="resp_..."``.
    - LangChainInstrumentor: ``output.value`` JSON has ``generations=[[..]]``
      and the id is nested under ``message.kwargs.response_metadata.id``.

    Args:
        attrs: OpenInference span attributes.

    Returns:
        The response id string, or ``None`` if not found.
    """
    if attrs is None:
        return None

    existing = attrs.get("gen_ai.response.id")
    if isinstance(existing, str) and existing:
        return existing

    output_value = attrs.get(OI.OUTPUT_VALUE)
    if not isinstance(output_value, str) or not output_value:
        return None

    try:
        payload = json.loads(output_value)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    response_id = payload.get("id")
    if isinstance(response_id, str) and response_id:
        return response_id

    return _extract_response_id_from_langchain_output(payload)


def extract_tool_definitions(
    attrs: Attributes | None,
) -> list[ToolDefinition]:
    """Extract ``gen_ai.tool.definitions`` from ``llm.tools.N.tool.json_schema``.

    Args:
        attrs: OpenInference span attributes.

    Returns:
        List of typed ToolDefinition models. Empty list if no tools are found.
    """
    tools: list[ToolDefinition] = []
    if attrs is None:
        return tools

    # Find all tool indices using the constant
    tool_pattern = re.compile(
        rf"{re.escape(OI.LLM_TOOLS)}\.(\d+)\.{re.escape(OI.TOOL_JSON_SCHEMA)}"
    )
    tool_indices = set()

    for key in attrs:
        match = tool_pattern.match(key)
        if match:
            tool_indices.add(int(match.group(1)))

    for idx in sorted(tool_indices):
        json_schema_key = f"{OI.LLM_TOOLS}.{idx}.{OI.TOOL_JSON_SCHEMA}"
        if json_schema_key in attrs:
            schema_value = attrs[json_schema_key]
            schema: dict[str, Any] | None = None

            # Parse JSON string or use dict directly
            if isinstance(schema_value, str):
                try:
                    schema = json.loads(schema_value)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Failed to parse tool schema: {schema_value}"
                    )
                    continue

            if schema is None:
                continue

            # LangChainInstrumentor encodes OpenAI tool schemas as:
            # {"type":"function","function":{"name":...,"description":...,"parameters":...}}
            if schema.get("type") == "function" and isinstance(
                schema.get("function"), dict
            ):
                fn = schema["function"]
                tools.append(
                    ToolDefinition(
                        type="function",
                        name=fn.get("name"),
                        description=fn.get("description"),
                        parameters=fn.get("parameters"),
                    )
                )
            else:
                tools.append(
                    ToolDefinition(
                        type=schema.get("type", "function"),
                        name=schema.get("name"),
                        description=schema.get("description"),
                        parameters=schema.get("parameters"),
                    )
                )

    return tools


def _extract_messages(
    attrs: Attributes | None, prefix: str, *, is_output: bool = False
) -> list[InputMessage] | list[OutputMessage]:
    """Extract messages from flattened attributes.

    Args:
        attrs: Flattened attributes (Attributes type or None)
        prefix: Either OI.LLM_INPUT_MESSAGES or OI.LLM_OUTPUT_MESSAGES
        is_output: If True, return OutputMessage instances instead of InputMessage

    Returns:
        List of typed message models
    """
    if attrs is None:
        return []

    # Intermediate accumulator — we need dicts internally for the regex parsing
    # since messages are reconstructed from many individual flattened keys.
    messages: dict[int, dict[str, Any]] = {}

    # Pattern to match message attributes: {prefix}.{idx}.message.{attr}
    base_pattern = re.compile(rf"{re.escape(prefix)}\.(\d+)\.message\.(.+)")

    for key, value in attrs.items():
        match = base_pattern.match(key)
        if not match:
            continue

        msg_idx = int(match.group(1))
        rest = match.group(2)

        if msg_idx not in messages:
            messages[msg_idx] = {
                "parts": [],
                "_tool_calls": {},
                "_contents": {},
            }

        msg = messages[msg_idx]

        # Handle different attribute types
        if rest == "role":
            msg["role"] = value
        elif rest == "content":
            if value:  # Only add if not empty
                msg["_has_content"] = True
                msg["_content_text"] = value
        elif rest == "tool_call_id":
            msg["_tool_call_id"] = value
        elif rest.startswith("tool_calls."):
            tc_match = re.match(r"tool_calls\.(\d+)\.tool_call\.(.+)", rest)
            if tc_match:
                tc_idx = int(tc_match.group(1))
                tc_attr = tc_match.group(2)

                if tc_idx not in msg["_tool_calls"]:
                    msg["_tool_calls"][tc_idx] = {}

                if tc_attr == "id":
                    msg["_tool_calls"][tc_idx]["id"] = value
                elif tc_attr == "function.name":
                    msg["_tool_calls"][tc_idx]["name"] = value
                elif tc_attr == "function.arguments":
                    msg["_tool_calls"][tc_idx]["arguments"] = value
        elif rest.startswith("contents."):
            c_match = re.match(r"contents\.(\d+)\.message_content\.(.+)", rest)
            if c_match:
                c_idx = int(c_match.group(1))
                c_attr = c_match.group(2)

                if c_idx not in msg["_contents"]:
                    msg["_contents"][c_idx] = {}

                if c_attr == "type":
                    msg["_contents"][c_idx]["type"] = value
                elif c_attr == "text":
                    msg["_contents"][c_idx]["text"] = value

    # Convert to typed models
    result_input: list[InputMessage] = []
    result_output: list[OutputMessage] = []

    for idx in sorted(messages.keys()):
        msg = messages[idx]
        role = msg.get("role", "assistant")
        parts: list[MessagePart] = []

        # Check if this is a tool response (role="tool" for OpenAI, role="user" with tool_call_id for Anthropic)
        if "_tool_call_id" in msg:
            content = msg.get("_content_text", "")
            try:
                response = json.loads(content) if content else None
            except json.JSONDecodeError:
                response = content

            parts.append(
                ToolCallResponsePart(
                    type="tool_call_response",
                    id=msg["_tool_call_id"],
                    response=response,
                )
            )
        else:
            # Handle contents array (multimodal)
            if msg["_contents"]:
                for c_idx in sorted(msg["_contents"].keys()):
                    content_block = msg["_contents"][c_idx]
                    if content_block.get("type") == "text":
                        parts.append(
                            TextPart(
                                type="text",
                                content=content_block.get("text", ""),
                            )
                        )

            # Handle simple text content
            if msg.get("_has_content") and msg.get("_content_text"):
                if not any(isinstance(p, TextPart) for p in parts):
                    parts.append(
                        TextPart(
                            type="text",
                            content=msg["_content_text"],
                        )
                    )

            # Handle tool calls
            for tc_idx in sorted(msg["_tool_calls"].keys()):
                tc = msg["_tool_calls"][tc_idx]
                parts.append(
                    ToolCallRequestPart(
                        type="tool_call",
                        id=tc.get("id"),
                        name=tc.get("name", ""),
                        arguments=tc.get("arguments"),
                    )
                )

        if is_output:
            result_output.append(
                OutputMessage(role=role, parts=parts, finish_reason=None)
            )
        else:
            result_input.append(InputMessage(role=role, parts=parts))

    if is_output:
        return result_output
    return result_input


def extract_system_instructions(
    attrs: Attributes | None,
) -> list[SystemInstruction]:
    """Extract ``gen_ai.system_instructions`` only when no system role exists.

    Logic:

    - If input messages have ``role="system"``, DON'T extract (keep in
      ``input_messages``).
    - Only populate if NO system role exists AND ``input.value`` has an
      ``"instructions"`` field (Responses API format).

    Args:
        attrs: OpenInference span attributes.

    Returns:
        List of typed SystemInstruction models, or empty list if not applicable.
    """
    if attrs is None:
        return []

    # If input messages have system role at index 0, extract the content
    # as a SystemInstruction (it will be filtered from input_messages below)
    first_msg_role_key = f"{OI.LLM_INPUT_MESSAGES}.0.message.role"
    if attrs.get(first_msg_role_key) == "system":
        content_key = f"{OI.LLM_INPUT_MESSAGES}.0.message.content"
        content = attrs.get(content_key)
        if isinstance(content, str) and content:
            return [SystemInstruction(type="text", content=content)]
        return []

    # No system role in messages - check input.value for system/instructions
    input_value = attrs.get(OI.INPUT_VALUE)
    if isinstance(input_value, str) and input_value:
        try:
            parsed = json.loads(input_value)
            # Anthropic format: {"system": "..."} or {"system": [{"type":"text","text":"..."}]}
            system = parsed.get("system")
            if system:
                if isinstance(system, str):
                    return [SystemInstruction(type="text", content=system)]
                if isinstance(system, list):
                    instructions = []
                    for block in system:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "text"
                        ):
                            instructions.append(
                                SystemInstruction(
                                    type="text", content=block["text"]
                                )
                            )
                    if instructions:
                        return instructions
            # OpenAI Responses API format: {"instructions": "..."}
            instructions_text = parsed.get("instructions")
            if instructions_text:
                return [
                    SystemInstruction(type="text", content=instructions_text)
                ]
        except json.JSONDecodeError:
            pass

    return []


def extract_input_messages(
    attrs: Attributes | None,
) -> tuple[list[InputMessage], list[SystemInstruction]]:
    """Extract ``gen_ai.input.messages`` and ``gen_ai.system_instructions``.

    Args:
        attrs: OpenInference span attributes.

    Returns:
        Tuple of ``(input_messages, system_instructions)`` as typed models.
    """
    system_instructions = extract_system_instructions(attrs)
    messages = _extract_messages(attrs, OI.LLM_INPUT_MESSAGES)
    # _extract_messages returns list[InputMessage] when is_output=False
    input_messages: list[InputMessage] = messages  # type: ignore[assignment]
    # If system instructions were extracted from the first message (role=system),
    # remove it from input_messages to avoid duplication
    if (
        system_instructions
        and input_messages
        and getattr(input_messages[0], "role", None) == "system"
    ):
        input_messages = input_messages[1:]
    return input_messages, system_instructions


def extract_output_messages(
    attrs: Attributes | None,
) -> list[OutputMessage]:
    """Extract ``gen_ai.output.messages`` from flattened output message attributes.

    Args:
        attrs: OpenInference span attributes.

    Returns:
        List of typed OutputMessage models.
    """
    messages = _extract_messages(attrs, OI.LLM_OUTPUT_MESSAGES, is_output=True)
    # _extract_messages returns list[OutputMessage] when is_output=True
    return messages  # type: ignore[return-value]


def convert_openinference_to_genai(
    attrs: Attributes | None,
) -> GenAiAttributes:
    """Convert OpenInference span attributes to GenAI semconv format.

    Args:
        attrs: OpenInference span attributes (Attributes type or None)

    Returns:
        GenAiAttributes with fields:
        - request_model (gen_ai.request.model): str or None
        - system (gen_ai.system): str or None
        - tool_definitions (gen_ai.tool.definitions): JSON string or None
        - input_messages (gen_ai.input.messages): JSON string or None
        - output_messages (gen_ai.output.messages): JSON string or None
        - system_instructions (gen_ai.system_instructions): JSON string or None
        - response_id (gen_ai.response.id): str or None
        - input_tokens (gen_ai.usage.input_tokens): int or None
        - output_tokens (gen_ai.usage.output_tokens): int or None
    """
    model_name = extract_model_name(attrs)
    system = extract_system(attrs)
    response_id = extract_response_id(attrs)
    tool_definitions = extract_tool_definitions(attrs)
    input_messages, system_instructions = extract_input_messages(attrs)
    output_messages = extract_output_messages(attrs)
    token_usage = extract_token_usage(attrs)

    # For TOOL spans, translate output.value → gen_ai.output.messages so the
    # frontend can display the tool result (it reads from GenAIOutputMessages).
    span_kind = (attrs or {}).get("openinference.span.kind")
    if span_kind == "TOOL" and not output_messages:
        output_value = (attrs or {}).get("output.value")
        if output_value:
            output_messages = [
                OutputMessage(
                    role="tool",
                    parts=[
                        ToolCallResponsePart(
                            type="tool_call_response",
                            response=output_value,
                        )
                    ],
                )
            ]

    return GenAiAttributes(
        request_model=model_name,
        system=system,
        tool_definitions=tool_definitions or None,
        input_messages=input_messages or None,
        output_messages=output_messages or None,
        system_instructions=system_instructions or None,
        response_id=response_id,
        input_tokens=token_usage.get("gen_ai.usage.input_tokens"),
        output_tokens=token_usage.get("gen_ai.usage.output_tokens"),
        cache_creation_input_tokens=token_usage.get(
            "gen_ai.usage.cache_creation.input_tokens"
        ),
        cache_read_input_tokens=token_usage.get(
            "gen_ai.usage.cache_read.input_tokens"
        ),
    )


def is_openinference_span(scope_name: str | None) -> bool:
    """Check if a span is from OpenInference instrumentation.

    Args:
        scope_name: The instrumentation_scope.name from the span

    Returns:
        True if the span is from OpenInference instrumentation
    """
    if not scope_name:
        return False
    return scope_name.startswith("openinference")


class ConvertedReadableSpan(ReadableSpan):
    """Wrapper for ReadableSpan that presents converted GenAI attributes.

    Since ReadableSpan is immutable after the span ends, this wrapper
    overrides the attributes property to return merged attributes while
    delegating all other properties to the original span.
    """

    def __init__(
        self,
        original_span: ReadableSpan,
        converted_attrs: GenAiAttributes,
        filter_prefixes: tuple[str, ...] = ("llm.", "input.", "output."),
    ):
        """Initialize with original span and converted attributes.

        Args:
            original_span: The original ReadableSpan to wrap
            converted_attrs: GenAiAttributes from conversion
            filter_prefixes: Attribute key prefixes to filter out (replaced by gen_ai.*)
        """
        self._original = original_span
        self._converted_attrs = converted_attrs
        self._filter_prefixes = filter_prefixes

    @property
    def attributes(self) -> Attributes:
        """Return merged attributes: filtered originals + converted GenAI."""
        merged: dict[str, Any] = {}

        # Copy attributes from original, skipping filtered prefixes
        if self._original.attributes:
            for key, value in self._original.attributes.items():
                if not key.startswith(self._filter_prefixes):
                    merged[key] = value

        # Add converted GenAI attributes using to_attributes() (excludes None values)
        merged.update(self._converted_attrs.to_attributes())

        # Ensure gen_ai.operation.name is set for LLM spans so the frontend
        # conversation view (which filters on GenAIOperationName = 'chat') shows them.
        if (self._original.attributes or {}).get(
            "openinference.span.kind"
        ) == "LLM":
            merged.setdefault("gen_ai.operation.name", "chat")

        return merged

    # ReadableSpan methods/properties that *must* delegate to avoid relying on
    # ReadableSpan's internal state (we intentionally don't call super().__init__).
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

    # Delegate all other properties to the original span
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
        # Fallback for any ReadableSpan surface we didn't explicitly proxy.
        return getattr(self._original, name)
