"""GenAI spans → an ATIF trajectory.

One projection, read by everything that needs a Harbor trajectory of a
conversation: the platform's ATIF export feeds it the spans it stores, and an
eval adapter feeds it the spans of a local run. Its only input is the GenAI
span the conversation reads return (:class:`GenAiSpan`), so a trajectory is a
function of the stored conversation and of nothing else.

Spans are read in chronological order. A model-call span becomes one ``agent``
step carrying its text, reasoning, tool calls and usage; the tool results that
arrive in a later span's input are attached to the step that made the call.
``gen_ai.input.messages`` may hold the whole prompt or only the turn's new
messages, so each span's input is aligned against what its agent has already
contributed and only the new messages become steps.

The caller chooses which spans to pass. Steps are one linear sequence, so a
conversation with delegated agents is normally read one agent at a time.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from introspection_sdk.schemas.atif import (
    AtifAgent,
    AtifFinalMetrics,
    AtifMetrics,
    AtifObservation,
    AtifObservationResult,
    AtifStep,
    AtifToolCall,
    AtifTrajectory,
)
from introspection_sdk.schemas.genai import (
    CompactionPart,
    InputMessage,
    OutputMessage,
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.schemas.genai_span import GenAiSpan

__all__ = ["AtifProjection", "spans_to_atif"]

_Message = InputMessage | OutputMessage

_UNKNOWN = "unknown"


def spans_to_atif(
    spans: Iterable[GenAiSpan],
    *,
    session_id: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
) -> AtifTrajectory:
    """Project a conversation's spans onto one ATIF trajectory.

    Spans are ordered by start time first, so a list read newest-first
    converts the same as one read oldest-first.

    Raises:
        ValueError: when the spans hold no message, or a tool call without
            an id. ATIF can represent neither.
    """
    projection = AtifProjection(
        session_id=session_id,
        agent_name=agent_name,
        agent_version=agent_version,
    )
    steps: list[AtifStep] = []
    for span in sorted(spans, key=lambda span: span.start_time):
        steps.extend(projection.add(span))
    steps.extend(projection.finish())
    return projection.trajectory(steps)


class AtifProjection:
    """Incremental form of :func:`spans_to_atif`, for a streamed read.

    Feed spans in chronological order with :meth:`add`; each call returns the
    steps that are now final. :meth:`finish` returns the rest, after which
    :attr:`agent`, :attr:`final_metrics` and :attr:`notes` are complete.

    A step with tool calls is held back until its agent's next model call has
    been read, because that call's input is where the results arrive.

    ``tool_statuses`` maps a tool call id to whether the call succeeded, for a
    caller that knows the outcomes before the spans stream past. Without it
    the outcome is read from the ``execute_tool`` spans, each of which ends
    before the model call that receives its result.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        agent_name: str | None = None,
        agent_version: str | None = None,
        tool_statuses: Mapping[str, bool] | None = None,
    ) -> None:
        self.session_id = session_id
        self._agent_name = agent_name
        self._agent_version = agent_version
        self._service_name: str | None = None
        self._tool_ok: dict[str, bool] = dict(tool_statuses or {})
        self._held: list[AtifStep] = []
        self._open: dict[str, list[AtifStep]] = {}
        self._calls: dict[str, AtifStep] = {}
        self._history: dict[str, list[str]] = {}
        self._instructions: set[tuple[str, ...]] = set()
        self._models: set[str] = set()
        self._step_count = 0
        self._omitted_parts = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._cached_tokens = 0
        self._cost_usd = 0.0

    def add(self, span: GenAiSpan) -> list[AtifStep]:
        """Read one span and return the steps it made final."""
        gen_ai = span.attributes.gen_ai
        if gen_ai is None:
            return []
        if self._agent_name is None and gen_ai.agent and gen_ai.agent.name:
            self._agent_name = gen_ai.agent.name
        if self._agent_version is None:
            self._agent_version = _resource_value(span, "service", "version")
        if self._service_name is None:
            self._service_name = _resource_value(span, "service", "name")
        if self.session_id is None:
            self.session_id = span.conversation_id

        self._record_tool_status(span)
        inputs = span.input_messages
        outputs = span.output_messages
        if not inputs and not outputs:
            return self._settled()

        lane = _lane(span)
        timestamp = span.start_time.isoformat().replace("+00:00", "Z")
        instructions = tuple(
            instruction.content.strip()
            for instruction in gen_ai.system_instructions or []
            if instruction.content.strip()
        )
        if instructions and instructions not in self._instructions:
            self._instructions.add(instructions)
            self._append(
                AtifStep(
                    step_id=self._next_id(),
                    timestamp=timestamp,
                    source="system",
                    message="\n\n".join(instructions),
                )
            )

        declared = (
            span.attributes.introspection.conversation.new_messages_start
            if span.attributes.introspection
            and span.attributes.introspection.conversation
            else None
        )
        for message in self._new_messages(lane, inputs, declared):
            self._input_step(lane, message, timestamp)
        # The results of this agent's earlier calls arrive in this input, so
        # whatever is still unanswered now stays unanswered.
        self._close(lane)

        if outputs:
            self._history.setdefault(lane, []).extend(
                _message_key(message) for message in outputs
            )
            self._agent_step(
                lane, outputs, timestamp, model=_model_name(span), span=span
            )
        return self._settled()

    def finish(self) -> list[AtifStep]:
        """Return the steps still held, and complete the totals."""
        for lane in list(self._open):
            self._close(lane)
        return self._settled()

    @property
    def agent(self) -> AtifAgent:
        """The producing agent; its model is set only when one was observed."""
        return AtifAgent(
            name=self._agent_name or self._service_name or _UNKNOWN,
            version=self._agent_version or _UNKNOWN,
            model_name=(
                next(iter(self._models)) if len(self._models) == 1 else None
            ),
        )

    @property
    def final_metrics(self) -> AtifFinalMetrics:
        return AtifFinalMetrics(
            total_prompt_tokens=self._prompt_tokens,
            total_completion_tokens=self._completion_tokens,
            total_cached_tokens=self._cached_tokens,
            total_cost_usd=self._cost_usd,
            total_steps=self._step_count,
        )

    @property
    def notes(self) -> str | None:
        """What the projection could not carry, or ``None``."""
        if not self._omitted_parts:
            return None
        return (
            f"{self._omitted_parts} non-text message part(s) were omitted: "
            "this projection writes text-only messages."
        )

    def trajectory(self, steps: list[AtifStep]) -> AtifTrajectory:
        """Assemble the trajectory from every step the projection returned."""
        if not steps:
            raise ValueError("the spans hold no message to project onto ATIF")
        return AtifTrajectory(
            session_id=self.session_id,
            agent=self.agent,
            steps=steps,
            notes=self.notes,
            final_metrics=self.final_metrics,
        )

    def _next_id(self) -> int:
        self._step_count += 1
        return self._step_count

    def _append(self, step: AtifStep) -> None:
        self._held.append(step)

    def _settled(self) -> list[AtifStep]:
        """Pop the leading steps no later result can still change."""
        waiting = {id(step) for steps in self._open.values() for step in steps}
        count = 0
        while count < len(self._held) and id(self._held[count]) not in waiting:
            count += 1
        settled, self._held = self._held[:count], self._held[count:]
        return settled

    def _close(self, lane: str) -> None:
        for step in self._open.pop(lane, []):
            for call in step.tool_calls or []:
                self._calls.pop(call.tool_call_id, None)

    def _record_tool_status(self, span: GenAiSpan) -> None:
        gen_ai = span.attributes.gen_ai
        call_id = (
            gen_ai.tool.call.id
            if gen_ai and gen_ai.tool and gen_ai.tool.call
            else None
        )
        code = span.status.code if span.status else None
        if not call_id or code not in ("Ok", "Error"):
            return
        self._tool_ok.setdefault(call_id, code == "Ok")

    def _new_messages(
        self,
        lane: str,
        messages: list[InputMessage],
        declared_start: int | None,
    ) -> list[InputMessage]:
        """The messages of ``messages`` this agent has not contributed yet.

        Also advances the agent's prompt history to ``messages``.
        """
        history = self._history.setdefault(lane, [])
        keys = [_message_key(message) for message in messages]
        lead = (
            1
            if len(messages) > 1
            and history
            and _is_compaction(messages[0])
            and keys[0] not in history
            else 0
        )
        offset, matched = _align(history, keys[lead:], declared_start)
        if lead:
            # A compacted prompt restarts the history at the summary; only
            # the retained tail can repeat what was already contributed.
            self._history[lane] = keys
            return [messages[0], *messages[lead + matched :]]
        if matched == len(keys) and matched > 1:
            # The same prompt again: a retried call adds nothing.
            return []
        if 0 < matched < len(keys):
            self._history[lane] = [*history[:offset], *keys]
            return messages[matched:]
        history.extend(keys)
        return messages

    def _input_step(
        self, lane: str, message: InputMessage, timestamp: str
    ) -> None:
        if message.role == "assistant":
            self._agent_step(lane, [message], timestamp, model=None, span=None)
            return
        text: list[str] = []
        for part in message.parts:
            if isinstance(part, TextPart | CompactionPart):
                if part.content:
                    text.append(part.content)
            elif isinstance(part, ToolCallResponsePart):
                self._attach_result(part, timestamp)
            elif not isinstance(part, ThinkingPart):
                self._omitted_parts += 1
        if text:
            self._append(
                AtifStep(
                    step_id=self._next_id(),
                    timestamp=timestamp,
                    source="system" if message.role == "system" else "user",
                    message="\n\n".join(text),
                )
            )

    def _attach_result(
        self, part: ToolCallResponsePart, timestamp: str
    ) -> None:
        response = part.response
        content = (
            response if isinstance(response, str) else json.dumps(response)
        )
        failed = part.id is not None and self._tool_ok.get(part.id) is False
        step = self._calls.get(part.id) if part.id else None
        if step is None:
            # ATIF only lets a result name a call of its own step, so a
            # result whose call was never read stands alone.
            extra: dict[str, Any] = (
                {"tool_call_id": part.id} if part.id else {}
            )
            if failed:
                extra["is_error"] = True
            self._append(
                AtifStep(
                    step_id=self._next_id(),
                    timestamp=timestamp,
                    source="system",
                    message="",
                    observation=AtifObservation(
                        results=[
                            AtifObservationResult(
                                content=content, extra=extra or None
                            )
                        ]
                    ),
                )
            )
            return
        result = AtifObservationResult(
            source_call_id=part.id,
            content=content,
            extra={"is_error": True} if failed else None,
        )
        if step.observation is None:
            step.observation = AtifObservation(results=[])
        step.observation.results.append(result)

    def _agent_step(
        self,
        lane: str,
        messages: list[Any],
        timestamp: str,
        *,
        model: str | None,
        span: GenAiSpan | None,
    ) -> None:
        text: list[str] = []
        reasoning: list[str] = []
        calls: list[AtifToolCall] = []
        for message in messages:
            for part in message.parts:
                if isinstance(part, TextPart | CompactionPart):
                    if part.content:
                        text.append(part.content)
                elif isinstance(part, ThinkingPart):
                    if part.content:
                        reasoning.append(part.content)
                elif isinstance(part, ToolCallRequestPart):
                    if not part.id:
                        raise ValueError(
                            "ATIF cannot represent a tool call without an id"
                        )
                    calls.append(
                        AtifToolCall(
                            tool_call_id=part.id,
                            function_name=part.name,
                            arguments=_arguments(part.arguments),
                        )
                    )
                else:
                    self._omitted_parts += 1
        step = AtifStep(
            step_id=self._next_id(),
            timestamp=timestamp,
            source="agent",
            model_name=model,
            message="\n\n".join(text),
            reasoning_content="\n\n".join(reasoning) or None,
            tool_calls=calls or None,
            metrics=self._metrics(span) if span is not None else None,
            llm_call_count=1 if span is not None else None,
        )
        if model:
            self._models.add(model)
        self._append(step)
        if calls:
            self._open.setdefault(lane, []).append(step)
            for call in calls:
                self._calls[call.tool_call_id] = step

    def _metrics(self, span: GenAiSpan) -> AtifMetrics:
        gen_ai = span.attributes.gen_ai
        usage = gen_ai.usage if gen_ai else None
        cost = gen_ai.cost.usd if gen_ai and gen_ai.cost else None
        prompt = usage.input_tokens if usage else None
        completion = usage.output_tokens if usage else None
        cached = (
            usage.cache_read.input_tokens
            if usage and usage.cache_read
            else None
        )
        self._prompt_tokens += prompt or 0
        self._completion_tokens += completion or 0
        self._cached_tokens += cached or 0
        self._cost_usd += cost or 0.0
        return AtifMetrics(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached_tokens=cached,
            cost_usd=cost,
        )


def _lane(span: GenAiSpan) -> str:
    """Prompt history is cumulative per agent, so it is kept per agent."""
    agent = span.attributes.gen_ai.agent if span.attributes.gen_ai else None
    if agent and agent.id:
        return f"id:{agent.id}"
    if agent and agent.name:
        return f"name:{agent.name}"
    return "root"


def _model_name(span: GenAiSpan) -> str | None:
    gen_ai = span.attributes.gen_ai
    if gen_ai is None:
        return None
    model = (gen_ai.response.model if gen_ai.response else None) or (
        gen_ai.request.model if gen_ai.request else None
    )
    if not model:
        return None
    provider = gen_ai.provider.name if gen_ai.provider else None
    return f"{provider}/{model}" if provider else model


def _resource_value(span: GenAiSpan, *path: str) -> str | None:
    """A resource attribute, whether the resource is nested or dotted."""
    resource = span.resource or {}
    flat = resource.get(".".join(path))
    if isinstance(flat, str) and flat:
        return flat
    node: Any = resource
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, str) and node else None


def _arguments(arguments: Any) -> dict[str, Any]:
    """Tool arguments as the object ATIF requires.

    A malformed or scalar value is kept under ``_raw``, as the trajectory-v1
    projection does, so the evidence survives.
    """
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return {"_raw": arguments}


def _is_compaction(message: Any) -> bool:
    return any(isinstance(part, CompactionPart) for part in message.parts)


def _message_key(message: Any) -> str:
    """Identity of a message for alignment.

    Reasoning is left out: a model's output carries it, the same message
    sent back as input may not.
    """
    parts: list[Any] = []
    for part in message.parts:
        if isinstance(part, ThinkingPart):
            continue
        if isinstance(part, TextPart | CompactionPart):
            parts.append([part.type, part.content])
        elif isinstance(part, ToolCallRequestPart):
            parts.append([part.type, part.id, part.name, part.arguments])
        elif isinstance(part, ToolCallResponsePart):
            parts.append([part.type, part.id, part.response])
        else:
            parts.append(part.model_dump(mode="json"))
    return json.dumps([message.role, parts], sort_keys=True, default=str)


def _align(
    history: list[str], keys: list[str], declared_start: int | None
) -> tuple[int, int]:
    """Where ``keys`` repeats ``history``: ``(offset, matched length)``.

    A prompt that repeats history either starts where the history starts (or
    where the span declares its new messages start), or runs to the history's
    end. Any other overlap is a coincidence, such as a user repeating an
    earlier message, and is not taken.
    """
    best = (0, 0)
    if not keys:
        return best
    anchored = {0}
    if declared_start is not None and 0 <= declared_start <= len(history):
        anchored.add(declared_start)
    for offset in range(len(history)):
        if history[offset] != keys[0]:
            continue
        limit = min(len(keys), len(history) - offset)
        matched = 0
        while matched < limit and history[offset + matched] == keys[matched]:
            matched += 1
        reaches_end = offset + matched == len(history)
        if (offset in anchored or reaches_end) and matched >= best[1]:
            best = (offset, matched)
    return best
