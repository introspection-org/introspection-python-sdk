"""Type definitions for the Introspection SDK."""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from introspection_sdk.schemas.genai import (
    InputMessage,
    OutputMessage,
    SystemInstruction,
    ToolDefinition,
)

__all__ = [
    "GenAiAttributes",
    "FeedbackProperties",
    "EventName",
    "Attr",
    "Baggage",
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


@dataclass
class FeedbackProperties:
    """Feedback event properties.

    Note: trace_id, span_id, identity, gen_ai.response.id, and gen_ai.conversation.id
    are automatically extracted from the current OpenTelemetry span/baggage.
    """

    name: str
    """Feedback name/action (e.g., "thumbs_up", "thumbs_down", "flag")"""

    comments: str | None = None
    """User's comments (e.g., "Answer was off topic")"""

    extra: dict[str, Any] = field(default_factory=dict)
    """Additional custom data"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values.

        Returns:
            Dict with ``"name"`` always present, optional ``"comments"``,
            plus any keys from :attr:`extra` merged in.
        """
        result: dict[str, Any] = {"name": self.name}
        if self.comments is not None:
            result["comments"] = self.comments
        result.update(self.extra)
        return result


def _generate_message_id() -> str:
    """Generate a unique event ID.

    Format: intro_event_<timestamp>-<random8>
    """
    timestamp = hex(int(time.time() * 1000))[2:]
    random_part = uuid.uuid4().hex[:8]
    return f"intro_event_{timestamp}-{random_part}"


class EventName:
    """Standard event names used by the Introspection SDK."""

    IDENTIFY = "identify"
    FEEDBACK = "introspection.feedback"


class Defaults:
    """Default configuration values."""

    SERVICE_NAME = "introspection-client"
    BASE_URL = "https://otel.introspection.dev"
    FLUSH_INTERVAL_MS = 5000
    MAX_BATCH_SIZE = 100


class Severity:
    """Log severity text constants."""

    INFO = "INFO"


class LoggerName:
    """Logger names for OpenTelemetry instrumentation scope."""

    PYTHON_SDK = "introspection-sdk"


class ApiPath:
    """API endpoint paths."""

    LOGS = "/v1/logs"


class Attr:
    """Standard log attribute keys used by the Introspection SDK.

    These follow OpenTelemetry semantic conventions where applicable.
    """

    # Core event fields
    EVENT_NAME = "event.name"
    EVENT_ID = "event.id"

    # Identity
    USER_ID = "identity.user.id"
    ANONYMOUS_ID = "identity.anonymous.id"

    # Gen AI (OTel semantic conventions)
    CONVERSATION_ID = "gen_ai.conversation.id"
    PREVIOUS_RESPONSE_ID = "gen_ai.request.previous_response_id"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_ID = "gen_ai.agent.id"

    # Prefixes for dynamic keys
    PROPERTIES_PREFIX = "properties."
    TRAITS_PREFIX = "context.traits."


class Baggage:
    """Baggage keys used for context propagation.

    Note: Identity keys use underscores instead of dots for baggage compatibility.
    """

    USER_ID = "identity.user_id"
    ANONYMOUS_ID = "identity.anonymous_id"
    CONVERSATION_ID = "gen_ai.conversation.id"
    PREVIOUS_RESPONSE_ID = "gen_ai.request.previous_response_id"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_ID = "gen_ai.agent.id"


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
