"""Type definitions for the Introspection SDK."""

import json
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field

from introspection_sdk.schemas.genai import (
    InputMessage,
    OutputMessage,
    SystemInstruction,
    ToolDefinition,
)

__all__ = [
    "GenAiAttributes",
    "GenAiSemconv",
    "OpenInferenceSemconv",
]


class GenAiAttributes(BaseModel):
    """OTel Gen AI semantic convention attributes for a single span.

    Wraps the standard ``gen_ai.*`` span attributes into a typed Pydantic
    model.  Field aliases correspond to the OTel semconv attribute keys.

    List fields (``input_messages``, ``output_messages``, ``system_instructions``,
    ``tool_definitions``) store typed Pydantic instances.  Converters pass
    ``list[dict]`` which Pydantic coerces automatically.
    Serialization to JSON strings is deferred to :meth:`to_attributes`.
    """

    model_config = ConfigDict(populate_by_name=True)

    request_model: str | None = Field(
        default=None,
        alias="gen_ai.request.model",
        description="Model name (e.g. 'gpt-4o', 'claude-sonnet-4-20250514').",
    )
    system: str | None = Field(
        default=None,
        alias="gen_ai.system",
        description="LLM provider identifier (e.g. 'openai', 'anthropic').",
    )
    tool_definitions: list[ToolDefinition] | None = Field(
        default=None,
        alias="gen_ai.tool.definitions",
        description="List of tool/function definitions.",
    )
    input_messages: list[InputMessage] | None = Field(
        default=None,
        alias="gen_ai.input.messages",
        description="List of input messages in semconv format.",
    )
    output_messages: list[OutputMessage] | None = Field(
        default=None,
        alias="gen_ai.output.messages",
        description="List of output messages in semconv format.",
    )
    system_instructions: list[SystemInstruction] | None = Field(
        default=None,
        alias="gen_ai.system_instructions",
        description="System instructions / system prompt parts.",
    )
    response_id: str | None = Field(
        default=None,
        alias="gen_ai.response.id",
        description="Unique identifier for the model response.",
    )
    input_tokens: int | None = Field(
        default=None,
        alias="gen_ai.usage.input_tokens",
        description="Number of input (prompt) tokens consumed.",
    )
    output_tokens: int | None = Field(
        default=None,
        alias="gen_ai.usage.output_tokens",
        description="Number of output (completion) tokens generated.",
    )
    cache_creation_input_tokens: int | None = Field(
        default=None,
        alias="gen_ai.usage.cache_creation.input_tokens",
        description="Tokens written to the prompt cache.",
    )
    cache_read_input_tokens: int | None = Field(
        default=None,
        alias="gen_ai.usage.cache_read.input_tokens",
        description="Tokens read from the prompt cache.",
    )
    agent_name: str | None = Field(
        default=None,
        alias="gen_ai.agent.name",
        description="Name of the parent agent/node that invoked this LLM call.",
    )

    def to_attributes(self) -> dict[str, str | int]:
        """Convert to dictionary with OTel semconv keys (dots), excluding None values.

        Scalar fields are emitted directly.  List fields are serialized to
        JSON strings at the export boundary.

        Returns:
            Dict keyed by dotted semconv attribute names
            (e.g. ``"gen_ai.request.model"``).  Only fields with
            non-``None`` values are included.
        """
        attrs: dict[str, str | int] = {}

        if self.request_model is not None:
            attrs[GenAiSemconv.REQUEST_MODEL] = self.request_model
        if self.system is not None:
            attrs[GenAiSemconv.SYSTEM] = self.system
            # ClickHouse reads GenAIProviderName from gen_ai.provider.name.
            # Emit both for compatibility with backends that use either key.
            attrs["gen_ai.provider.name"] = self.system
        if self.response_id is not None:
            attrs[GenAiSemconv.RESPONSE_ID] = self.response_id
        if self.input_tokens is not None:
            attrs[GenAiSemconv.INPUT_TOKENS] = self.input_tokens
        if self.output_tokens is not None:
            attrs[GenAiSemconv.OUTPUT_TOKENS] = self.output_tokens
        if self.cache_creation_input_tokens is not None:
            attrs["gen_ai.usage.cache_creation.input_tokens"] = (
                self.cache_creation_input_tokens
            )
        if self.cache_read_input_tokens is not None:
            attrs["gen_ai.usage.cache_read.input_tokens"] = (
                self.cache_read_input_tokens
            )
        if self.agent_name is not None:
            attrs["gen_ai.agent.name"] = self.agent_name

        if self.input_messages is not None:
            attrs[GenAiSemconv.INPUT_MESSAGES] = json.dumps(
                [m.model_dump(exclude_none=True) for m in self.input_messages]
            )
        if self.output_messages is not None:
            attrs[GenAiSemconv.OUTPUT_MESSAGES] = json.dumps(
                [m.model_dump(exclude_none=True) for m in self.output_messages]
            )
        if self.system_instructions is not None:
            attrs[GenAiSemconv.SYSTEM_INSTRUCTIONS] = json.dumps(
                [
                    m.model_dump(exclude_none=True)
                    for m in self.system_instructions
                ]
            )
        if self.tool_definitions is not None:
            attrs[GenAiSemconv.TOOL_DEFINITIONS] = json.dumps(
                [
                    m.model_dump(exclude_none=True)
                    for m in self.tool_definitions
                ]
            )

        return attrs


def _generate_message_id() -> str:
    """Generate a unique event ID.

    Format: intro_event_<timestamp>-<random8>
    """
    timestamp = hex(int(time.time() * 1000))[2:]
    random_part = uuid.uuid4().hex[:8]
    return f"intro_event_{timestamp}-{random_part}"


class GenAiSemconv:
    """OTel Gen AI semantic convention attribute keys."""

    REQUEST_MODEL = "gen_ai.request.model"
    SYSTEM = "gen_ai.system"
    RESPONSE_ID = "gen_ai.response.id"
    INPUT_TOKENS = "gen_ai.usage.input_tokens"
    OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    INPUT_MESSAGES = "gen_ai.input.messages"
    OUTPUT_MESSAGES = "gen_ai.output.messages"
    SYSTEM_INSTRUCTIONS = "gen_ai.system_instructions"
    TOOL_DEFINITIONS = "gen_ai.tool.definitions"


class OpenInferenceSemconv:
    """OpenInference semantic convention attribute keys.

    Defined inline to avoid requiring the openinference-semantic-conventions package.
    """

    SPAN_KIND = "openinference.span.kind"
    LLM_MODEL_NAME = "llm.model_name"
    LLM_SYSTEM = "llm.system"
    LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
    LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
    LLM_TOOLS = "llm.tools"
    LLM_INPUT_MESSAGES = "llm.input_messages"
    LLM_OUTPUT_MESSAGES = "llm.output_messages"
    INPUT_VALUE = "input.value"
    OUTPUT_VALUE = "output.value"
    TOOL_JSON_SCHEMA = "tool.json_schema"
