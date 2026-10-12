"""Agent Trajectory Interchange Format (ATIF) — the subset this SDK writes.

ATIF is Harbor's trajectory format: an object with ``schema_version``,
``agent`` and sequential ``steps``. It is distinct from the trajectory-v1
record array in :mod:`introspection_sdk.schemas.trajectory`.

Like trajectory-v1, an ATIF trajectory is a **projection** of the GenAI spans
stored for a conversation (see :mod:`introspection_sdk.atif`), never a second
storage format.

These models declare only the fields the projection writes, at one pinned
``schema_version``. Harbor owns the format; ``tests/fixtures/atif.schema.json``
is Harbor's own schema, and every trajectory the projection produces is
validated against it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

__all__ = [
    "ATIF_SCHEMA_VERSION",
    "AtifAgent",
    "AtifFinalMetrics",
    "AtifMetrics",
    "AtifObservation",
    "AtifObservationResult",
    "AtifStep",
    "AtifToolCall",
    "AtifTrajectory",
]

#: The newest ATIF version whose fields the projection uses: the result-level
#: ``extra`` and ``llm_call_count`` both arrived in v1.7.
ATIF_SCHEMA_VERSION: Literal["ATIF-v1.7"] = "ATIF-v1.7"


class _AtifModel(BaseModel):
    """Closed, omit-absent base: Harbor's models forbid unknown fields."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> Any:
        serialized = handler(self)
        if not isinstance(serialized, dict):
            return serialized
        return {
            key: value
            for key, value in serialized.items()
            if value is not None
        }


class AtifToolCall(_AtifModel):
    """One tool invocation of an agent step."""

    tool_call_id: str
    function_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AtifObservationResult(_AtifModel):
    """The result of one tool call.

    ATIF has no error field on a result. A failed call is marked
    ``extra: {"is_error": true}``; a successful one carries no ``extra``.
    """

    source_call_id: str | None = None
    content: str | None = None
    extra: dict[str, Any] | None = None


class AtifObservation(_AtifModel):
    """The tool results an agent step received."""

    results: list[AtifObservationResult]


class AtifMetrics(_AtifModel):
    """Usage of one model call.

    ``prompt_tokens`` includes cached tokens, as ``gen_ai.usage.input_tokens``
    does.
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None


class AtifStep(_AtifModel):
    """One step: a system prompt, a user turn, or one model call."""

    step_id: int = Field(ge=1)
    timestamp: str | None = None
    source: Literal["system", "user", "agent"]
    model_name: str | None = None
    message: str
    reasoning_content: str | None = None
    tool_calls: list[AtifToolCall] | None = None
    observation: AtifObservation | None = None
    metrics: AtifMetrics | None = None
    llm_call_count: int | None = Field(default=None, ge=0)


class AtifAgent(_AtifModel):
    """The agent system that produced the trajectory."""

    name: str
    version: str
    model_name: str | None = None


class AtifFinalMetrics(_AtifModel):
    """Totals over every step."""

    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    total_cached_tokens: int | None = None
    total_cost_usd: float | None = None
    total_steps: int | None = Field(default=None, ge=0)


class AtifTrajectory(_AtifModel):
    """An ATIF trajectory: Harbor's object-root contract."""

    schema_version: Literal["ATIF-v1.7"] = ATIF_SCHEMA_VERSION
    session_id: str | None = None
    agent: AtifAgent
    steps: list[AtifStep] = Field(min_length=1)
    notes: str | None = None
    final_metrics: AtifFinalMetrics | None = None
