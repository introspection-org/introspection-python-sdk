"""trajectory-v1 records — the interchange view of a conversation.

A trajectory is a **projection derived on read** from the GenAI messages
already stored for a conversation, not a second storage format. Nothing
accepts a trajectory as input; it exists only as an export representation,
which is why these models are read-only and have no ``*Create`` twins.

The record vocabulary is deliberately small and matches the pinned
``trajectory-v1`` contract: a leading ``meta`` record, then ``user``,
``reasoning``, ``assistant`` (prose or tool calls), and ``tool`` records
linked by ``tool_call_id``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Trajectory",
    "TrajectoryAssistantRecord",
    "TrajectoryMetaRecord",
    "TrajectoryReasoningRecord",
    "TrajectoryRecord",
    "TrajectoryToolCall",
    "TrajectoryToolRecord",
    "TrajectoryUserRecord",
]


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TrajectoryToolCall(_ApiModel):
    """One tool invocation inside a :class:`TrajectoryAssistantRecord`.

    ``args`` is a **JSON-encoded string**, not an object. That is the
    upstream contract rather than an oversight here: the encoded value is
    an object, and a malformed or scalar source value arrives as
    ``{"_raw": ...}`` so the evidence survives without breaking the schema.
    """

    id: str
    name: str
    args: str


class TrajectoryMetaRecord(_ApiModel):
    """Leading record identifying the session the trajectory came from."""

    role: Literal["meta"] = "meta"
    source: str
    cwd: str | None = None
    git_branch: str | None = None
    model: str | None = None


class TrajectoryUserRecord(_ApiModel):
    """A user turn."""

    role: Literal["user"] = "user"
    content: str
    timestamp: str


class TrajectoryReasoningRecord(_ApiModel):
    """Model reasoning, when the source exposed it."""

    role: Literal["reasoning"] = "reasoning"
    content: str
    timestamp: str


class TrajectoryAssistantRecord(_ApiModel):
    """An assistant turn — prose, or tool calls, never both.

    The two are distinguished by ``content``: a prose record carries text
    and no ``tool_calls``; a tool-call record carries ``content: null``.
    That null is load-bearing and always present on the wire, so it is
    typed ``str | None`` rather than omitted.
    """

    role: Literal["assistant"] = "assistant"
    content: str | None
    timestamp: str
    tool_calls: list[TrajectoryToolCall] | None = None


class TrajectoryToolRecord(_ApiModel):
    """A tool result, linked to its call by ``tool_call_id``."""

    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str
    timestamp: str
    ok: bool | None = None


#: One record in a trajectory-v1 export, discriminated by ``role``.
TrajectoryRecord = Annotated[
    TrajectoryMetaRecord
    | TrajectoryUserRecord
    | TrajectoryReasoningRecord
    | TrajectoryAssistantRecord
    | TrajectoryToolRecord,
    Field(discriminator="role"),
]

#: The trajectory-v1 wire shape: a non-empty top-level array of records.
Trajectory = list[TrajectoryRecord]
