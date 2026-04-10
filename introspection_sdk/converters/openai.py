"""OpenAI format conversion functions for OTel Gen AI Semantic Conventions.

These functions convert OpenAI API formats (Responses API, Agents SDK) to the
standardized OTel Gen AI Semantic Convention format for gen_ai.input.messages
and gen_ai.output.messages attributes.
"""

from __future__ import annotations

__all__ = [
    "convert_responses_inputs_to_semconv",
    "convert_responses_outputs_to_semconv",
]

from collections.abc import Sequence

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

try:
    from openai.types.responses import (
        ResponseFunctionToolCall,
        ResponseFunctionWebSearch,
        ResponseInputItemParam,
        ResponseOutputItem,
        ResponseOutputMessage,
        ResponseReasoningItem,
    )
    from openai.types.responses.response_output_item import McpCall
    from openai.types.responses.response_output_text import ResponseOutputText
except ImportError:
    McpCall = None  # type: ignore[invalid-assignment]
    ResponseFunctionToolCall = None  # type: ignore[invalid-assignment]
    ResponseFunctionWebSearch = None  # type: ignore[invalid-assignment]
    ResponseInputItemParam = None  # type: ignore[invalid-assignment]
    ResponseOutputItem = None  # type: ignore[invalid-assignment]
    ResponseOutputMessage = None  # type: ignore[invalid-assignment]
    ResponseReasoningItem = None  # type: ignore[invalid-assignment]
    ResponseOutputText = None  # type: ignore[invalid-assignment]


def _extract_content_parts(
    content: str | Sequence[object] | None,
) -> list[MessagePart]:
    """Extract message parts from content (str, sequence, or typed objects).

    Handles typed OpenAI content objects — both Pydantic models
    (``ResponseOutputText``) and TypedDicts (``ResponseInputTextParam``) —
    as well as plain strings.
    """
    parts: list[MessagePart] = []
    if content is None:
        return parts

    if isinstance(content, str):
        parts.append(TextPart(type="text", content=content))
        return parts

    for item in content:
        if isinstance(item, str):
            parts.append(TextPart(type="text", content=item))
        elif isinstance(item, dict):
            # TypedDict content items (e.g. ResponseInputTextParam)
            text = item.get("text", item.get("content", ""))  # type: ignore[arg-type]
            if text:
                parts.append(TextPart(type="text", content=str(text)))
        elif ResponseOutputText is not None and isinstance(
            item, ResponseOutputText
        ):
            parts.append(TextPart(type="text", content=item.text))
        else:
            # Other typed content objects — extract text if available
            text = getattr(item, "text", None)
            if text:
                parts.append(TextPart(type="text", content=str(text)))

    return parts


def _convert_input_item(
    inp: ResponseInputItemParam,
) -> tuple[InputMessage | None, SystemInstruction | None]:
    """Convert an OpenAI ResponseInputItemParam to semconv models.

    All ``ResponseInputItemParam`` members are TypedDicts (subclass of dict),
    so dict-style ``.get()`` access works on typed SDK objects directly.

    Returns:
        Tuple of (input_message, system_instruction). At most one is set.
    """
    role = inp.get("role", "user")
    typ = inp.get("type")
    content = inp.get("content")

    if typ in (None, "message") and content:
        parts = _extract_content_parts(content)  # type: ignore[invalid-argument-type]
        if parts:
            # Map OpenAI "developer" role to semconv "system"
            mapped_role = "system" if role == "developer" else role
            return InputMessage(role=mapped_role, parts=parts), None

    elif typ == "function_call":
        return InputMessage(
            role="assistant",
            parts=[
                ToolCallRequestPart(
                    type="tool_call",
                    id=inp.get("call_id"),
                    name=inp.get("name", ""),
                    arguments=inp.get("arguments"),
                )
            ],
        ), None

    elif typ == "function_call_output":
        return InputMessage(
            role="tool",
            parts=[
                ToolCallResponsePart(
                    type="tool_call_response",
                    id=inp.get("call_id"),
                    response=inp.get("output"),
                )
            ],
            name=inp.get("name"),
        ), None

    return None, None


def convert_responses_inputs_to_semconv(
    inputs: str | Sequence[ResponseInputItemParam] | None,
    instructions: str | None,
) -> tuple[list[InputMessage], list[SystemInstruction]]:
    """Convert Responses API inputs to OTel Gen AI Semantic Convention format.

    Accepts typed OpenAI ``ResponseInputItemParam`` objects (TypedDicts).

    Args:
        inputs: List of input items from the request, or a plain string prompt.
        instructions: System instructions/prompt.

    Returns:
        Tuple of (input_messages, system_instructions) as typed models.
    """
    input_messages: list[InputMessage] = []
    system_instructions: list[SystemInstruction] = []

    if instructions:
        system_instructions.append(
            SystemInstruction(type="text", content=instructions)
        )

    if inputs:
        # ResponseSpanData.input can be a plain string
        if isinstance(inputs, str):
            input_messages.append(
                InputMessage(
                    role="user",
                    parts=[TextPart(type="text", content=inputs)],
                )
            )
            return input_messages, system_instructions

        for inp in inputs:
            msg, sys_instr = _convert_input_item(inp)

            if msg:
                input_messages.append(msg)
            if sys_instr:
                system_instructions.append(sys_instr)

    return input_messages, system_instructions


def _convert_output_item(
    out: ResponseOutputItem,
) -> OutputMessage | None:
    """Convert a typed OpenAI ResponseOutputItem to an OutputMessage.

    All ``ResponseOutputItem`` members are Pydantic models, so attribute
    access is used throughout.
    """
    if ResponseOutputMessage is not None and isinstance(
        out, ResponseOutputMessage
    ):
        parts = _extract_content_parts(out.content)
        finish_reason = "stop" if out.status == "completed" else None
        if parts:
            return OutputMessage(
                role="assistant", parts=parts, finish_reason=finish_reason
            )

    elif ResponseFunctionToolCall is not None and isinstance(
        out, ResponseFunctionToolCall
    ):
        return OutputMessage(
            role="assistant",
            finish_reason="tool-calls",
            parts=[
                ToolCallRequestPart(
                    type="tool_call",
                    id=out.call_id,
                    name=out.name,
                    arguments=out.arguments,
                )
            ],
        )

    elif ResponseReasoningItem is not None and isinstance(
        out, ResponseReasoningItem
    ):
        summary_texts = [s.text for s in out.summary if s.text]
        content = "\n".join(summary_texts) if summary_texts else None
        signature = out.encrypted_content or None
        return OutputMessage(
            role="assistant",
            parts=[
                ThinkingPart(
                    type="thinking",
                    content=content,
                    signature=signature,
                    provider_name="openai",
                )
            ],
        )

    elif ResponseFunctionWebSearch is not None and isinstance(
        out, ResponseFunctionWebSearch
    ):
        return OutputMessage(
            role="assistant",
            parts=[
                ToolCallRequestPart(
                    type="tool_call",
                    id=out.id,
                    name="web_search",
                )
            ],
        )

    return None


def convert_responses_outputs_to_semconv(
    outputs: Sequence[ResponseOutputItem],
) -> list[OutputMessage]:
    """Convert Responses API outputs to OTel Gen AI Semantic Convention format.

    Accepts typed OpenAI ``ResponseOutputItem`` objects (Pydantic models).

    Reasoning and web_search_call parts are merged into the adjacent message's
    parts array (rather than emitted as separate messages) so that the frontend
    renders them together with the text response.

    Args:
        outputs: List of output items from the response.

    Returns:
        List of output messages as typed models.
    """
    # First pass: collect all parts, merging reasoning/web_search into
    # the message they accompany (typically the last message item).
    prefix_parts: list[MessagePart] = []
    output_messages: list[OutputMessage] = []
    pending_web_search_id: str | None = None

    for out in outputs:
        if ResponseReasoningItem is not None and isinstance(
            out, ResponseReasoningItem
        ):
            summary_texts = [s.text for s in out.summary if s.text]
            content = "\n".join(summary_texts) if summary_texts else None
            signature = out.encrypted_content or None
            prefix_parts.append(
                ThinkingPart(
                    type="thinking",
                    content=content,
                    signature=signature,
                    provider_name="openai",
                )
            )

        elif McpCall is not None and isinstance(out, McpCall):
            tool_name = (
                f"{out.server_label}/{out.name}"
                if out.server_label
                else out.name
            )
            prefix_parts.append(
                ToolCallRequestPart(
                    type="tool_call",
                    id=out.id,
                    name=tool_name,
                    arguments=out.arguments,
                )
            )
            result = out.error if out.error else (out.output or "")
            prefix_parts.append(
                ToolCallResponsePart(
                    type="tool_call_response",
                    id=out.id,
                    response=result,
                )
            )

        elif getattr(out, "type", None) == "mcp_list_tools":
            # Skip — tool discovery metadata, not a user-facing message
            pass

        elif ResponseFunctionWebSearch is not None and isinstance(
            out, ResponseFunctionWebSearch
        ):
            query = getattr(out.action, "query", None) if out.action else None
            args = f'{{"query": "{query}"}}' if query else None
            prefix_parts.append(
                ToolCallRequestPart(
                    type="tool_call",
                    id=out.id,
                    name="web_search",
                    arguments=args,
                )
            )
            pending_web_search_id = out.id

        elif ResponseOutputMessage is not None and isinstance(
            out, ResponseOutputMessage
        ):
            # Extract search result citations from annotations if this follows a web search
            if pending_web_search_id:
                citations: list[str] = []
                for c in out.content:
                    for ann in getattr(c, "annotations", []):
                        title = getattr(ann, "title", None)
                        url = getattr(ann, "url", None)
                        if title and url:
                            citations.append(f"{title}: {url}")
                result_text = (
                    "\n".join(citations) if citations else "search completed"
                )
                prefix_parts.append(
                    ToolCallResponsePart(
                        type="tool_call_response",
                        id=pending_web_search_id,
                        response=result_text,
                    )
                )
                pending_web_search_id = None

            msg = _convert_output_item(out)
            if msg and prefix_parts:
                msg = OutputMessage(
                    role=msg.role,
                    parts=[*prefix_parts, *msg.parts],
                    finish_reason=msg.finish_reason,
                )
                prefix_parts = []
            if msg:
                output_messages.append(msg)

        else:
            msg = _convert_output_item(out)
            if msg and prefix_parts:
                msg = OutputMessage(
                    role=msg.role,
                    parts=[*prefix_parts, *msg.parts],
                    finish_reason=msg.finish_reason,
                )
                prefix_parts = []
            if msg:
                output_messages.append(msg)

    # If there are leftover prefix parts with no message to attach to,
    # emit them as a standalone message
    if prefix_parts:
        output_messages.append(
            OutputMessage(role="assistant", parts=prefix_parts)
        )

    return output_messages
