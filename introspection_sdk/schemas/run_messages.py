"""AG-UI messages that open a task's conversation.

``POST /v1/tasks/{id}/runs`` takes ``messages`` in place of ``prompt``: every
message but the last is loaded into the session without a model call, and the
last, a user message, runs as the turn's prompt. The server accepts them only
while the task's conversation is empty.

The list is a union discriminated on ``role``. AG-UI's camelCase names
(``toolCalls``, ``toolCallId``) are the wire names; these models take either
spelling and write camelCase. They mirror the server's request schema, which
is narrower than AG-UI's own messages: text content only, and no ``name`` or
``encryptedValue``.

The server answers 422 unless the list is non-empty, its last message is a
user message, every tool message answers an earlier tool call and every tool
call is answered, and its UTF-8 JSON is at most 1 MiB.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

__all__ = [
    "RunAssistantMessage",
    "RunFunctionCall",
    "RunMessage",
    "RunToolCall",
    "RunToolMessage",
    "RunUserMessage",
    "run_messages_wire",
]


class RunMessageModel(BaseModel):
    """camelCase on the wire, either spelling in Python."""

    model_config = ConfigDict(populate_by_name=True)


class RunFunctionCall(RunMessageModel):
    """The function an AG-UI tool call names."""

    name: str = Field(min_length=1)
    arguments: str
    """The tool's arguments, JSON-encoded."""


class RunToolCall(RunMessageModel):
    """One tool call on an assistant message."""

    id: str = Field(min_length=1)
    """The id the tool message that answers it names."""
    type: Literal["function"] = "function"
    function: RunFunctionCall


class RunUserMessage(RunMessageModel):
    """A user message. The last message of a run's ``messages`` is one."""

    id: str = Field(min_length=1)
    role: Literal["user"] = "user"
    content: str = Field(min_length=1)


class RunAssistantMessage(RunMessageModel):
    """An assistant message: text, tool calls, or both."""

    id: str = Field(min_length=1)
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[RunToolCall] | None = Field(
        default=None,
        validation_alias=AliasChoices("toolCalls", "tool_calls"),
        serialization_alias="toolCalls",
    )

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if not self.content and not self.tool_calls:
            raise ValueError("an assistant message needs content or toolCalls")
        return self


class RunToolMessage(RunMessageModel):
    """The result of one earlier tool call."""

    id: str = Field(min_length=1)
    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("toolCallId", "tool_call_id"),
        serialization_alias="toolCallId",
    )
    error: str | None = None
    """Set when the call failed."""


RunMessage = Annotated[
    RunUserMessage | RunAssistantMessage | RunToolMessage,
    Field(discriminator="role"),
]
"""One message of a run's ``messages``, discriminated on ``role``."""


def run_messages_wire(
    messages: Sequence[RunMessage | dict[str, Any]],
) -> list[dict[str, Any]]:
    """``messages`` as the request body holds them: camelCase, nulls left out.

    A dict is sent as given.
    """
    return [
        message.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(message, BaseModel)
        else message
        for message in messages
    ]
