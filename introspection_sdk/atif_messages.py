"""An ATIF trajectory → the AG-UI messages that open a run.

A Harbor adapter's ``load()`` seeds an agent's session from a previous
trajectory (Harbor's ``trajectory.json``) and then runs the task instruction.
On Introspection that is one call: :func:`atif_to_run_messages` turns the
trajectory into run ``messages``, with the instruction as the last user
message, and ``tasks.runs.create(task_id, messages=...)`` loads every message
but the last into an empty conversation and runs the last as the prompt.

What maps, step by step, in order:

- a ``user`` step becomes a user message;
- an ``agent`` step becomes an assistant message with its text and tool
  calls, followed by one tool message per observation result, paired with
  its call by ``source_call_id``. A result marked ``extra.is_error`` carries
  its content as the tool message's ``error`` too;
- a ``system`` step is left out, as Harbor's own loaders leave it out: the
  Runtime's recipe owns the system prompt.

Reasoning, metrics and ``extra`` have no AG-UI field and are left out, and
an agent step with neither text nor tool calls adds no message. Anything
else that the messages cannot carry raises :class:`AtifConversionError`
rather than being dropped: a tool call without exactly one result in its own
step, a result naming no call of its step, non-text content, an empty user
message, and a list whose last message is not a user message.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from introspection_sdk.schemas.run_messages import (
    RunAssistantMessage,
    RunFunctionCall,
    RunMessage,
    RunToolCall,
    RunToolMessage,
    RunUserMessage,
)

__all__ = ["AtifConversionError", "atif_to_run_messages"]


class AtifConversionError(ValueError):
    """The trajectory holds something run ``messages`` cannot express.

    ``step_id`` names the step at fault, or is ``None`` when the fault is the
    trajectory as a whole.
    """

    def __init__(self, message: str, *, step_id: int | None = None) -> None:
        super().__init__(
            message if step_id is None else f"step {step_id}: {message}"
        )
        self.step_id = step_id


def atif_to_run_messages(
    trajectory: Mapping[str, Any] | BaseModel,
    *,
    prompt: str | None = None,
) -> list[RunMessage]:
    """The run ``messages`` that load ``trajectory`` and then run ``prompt``.

    ``trajectory`` is an ATIF trajectory: the parsed ``trajectory.json``, an
    :class:`~introspection_sdk.schemas.atif.AtifTrajectory`, or Harbor's own
    ``Trajectory`` model. Only its own ``steps`` are read, never a subagent's
    trajectory.

    ``prompt``, the task instruction, is appended as the last user message.
    Without it the trajectory's last kept step must be a user step, which
    then runs as the prompt.

    Raises:
        AtifConversionError: a step the messages cannot express (see the
            module docstring), or no user message last.
    """
    data = (
        trajectory.model_dump(mode="json")
        if isinstance(trajectory, BaseModel)
        else trajectory
    )
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise AtifConversionError("the trajectory has no steps list")
    messages: list[RunMessage] = []
    for step in steps:
        messages.extend(_step_messages(step))
    if prompt is not None:
        messages.append(RunUserMessage(id="prompt", content=prompt))
    if not messages or not isinstance(messages[-1], RunUserMessage):
        raise AtifConversionError(
            "the last message must be a user message: pass the task "
            "instruction as prompt"
        )
    return messages


def _step_messages(step: Mapping[str, Any]) -> list[RunMessage]:
    step_id = step.get("step_id")
    source = step.get("source")
    if source == "system":
        return []
    text = _text(step.get("message"), step_id)
    if source == "user":
        if step.get("tool_calls") or step.get("observation"):
            raise AtifConversionError(
                "a user step with tool calls or an observation has no "
                "message form",
                step_id=step_id,
            )
        if not text:
            raise AtifConversionError(
                "a user message needs text", step_id=step_id
            )
        return [RunUserMessage(id=f"atif-step-{step_id}", content=text)]
    if source == "agent":
        return _agent_messages(step, step_id, text)
    raise AtifConversionError(
        f"unknown step source {source!r}", step_id=step_id
    )


def _agent_messages(
    step: Mapping[str, Any], step_id: Any, text: str
) -> list[RunMessage]:
    calls = [
        _tool_call(call, step_id) for call in step.get("tool_calls") or []
    ]
    if not text and not calls:
        return []
    messages: list[RunMessage] = [
        RunAssistantMessage(
            id=f"atif-step-{step_id}",
            content=text or None,
            tool_calls=calls or None,
        )
    ]
    results = _results_by_call(step, step_id, {call.id for call in calls})
    for call in calls:
        result = results.get(call.id)
        if result is None:
            raise AtifConversionError(
                f"tool call {call.id!r} has no result in its step",
                step_id=step_id,
            )
        content = _text(result.get("content"), step_id)
        failed = bool((result.get("extra") or {}).get("is_error"))
        messages.append(
            RunToolMessage(
                id=f"atif-step-{step_id}-result-{call.id}",
                content=content,
                tool_call_id=call.id,
                error=(content or "the tool call failed") if failed else None,
            )
        )
    return messages


def _tool_call(call: Mapping[str, Any], step_id: Any) -> RunToolCall:
    call_id = call.get("tool_call_id")
    name = call.get("function_name")
    if not call_id or not name:
        raise AtifConversionError(
            "a tool call needs a tool_call_id and a function_name",
            step_id=step_id,
        )
    return RunToolCall(
        id=call_id,
        function=RunFunctionCall(
            name=name, arguments=json.dumps(call.get("arguments") or {})
        ),
    )


def _results_by_call(
    step: Mapping[str, Any], step_id: Any, call_ids: set[str]
) -> dict[str, Mapping[str, Any]]:
    observation = step.get("observation") or {}
    results: dict[str, Mapping[str, Any]] = {}
    for result in observation.get("results") or []:
        call_id = result.get("source_call_id")
        if call_id not in call_ids:
            raise AtifConversionError(
                f"observation result for {call_id!r} names no tool call of "
                "its step",
                step_id=step_id,
            )
        if call_id in results:
            raise AtifConversionError(
                f"tool call {call_id!r} has more than one result",
                step_id=step_id,
            )
        results[call_id] = result
    return results


def _text(content: Any, step_id: Any) -> str:
    """A message or result as text; ATIF's text-only part lists join."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(part, Mapping) and part.get("type") == "text"
        for part in content
    ):
        return "\n\n".join(str(part.get("text") or "") for part in content)
    raise AtifConversionError(
        "non-text content (an image or other part) has no message form",
        step_id=step_id,
    )
