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

An ``execute_tool`` span adds what the prompt does not hold. Its structured
``gen_ai.tool.call.result`` goes into the observation result of the same call,
under ``extra.details``, beside the ``content`` the model read: ATIF has no
field of its own for it, and ``extra`` is the format's place for custom
result-level metadata. A tool result the prompt never echoed, such as a
session's last tool call, becomes an observation result from the span alone.
The span may be read before or after the spans holding the call and the result.

The caller chooses which spans to pass. Steps are one linear sequence, so a
conversation with delegated agents is normally read one agent at a time.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
    TextPart,
    ThinkingPart,
    ToolCallRequestPart,
    ToolCallResponsePart,
)
from introspection_sdk.schemas.genai_span import GenAiSpan

__all__ = ["AtifProjection", "spans_to_atif"]

UNKNOWN = "unknown"

#: The keys of an agent framework's tool result, ``{content, details}`` on Pi:
#: only ``details`` is structured, ``content`` is the text the model reads.
TOOL_RESULT_ENVELOPE = frozenset({"content", "details", "isError"})


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
    ordered = sorted(spans, key=lambda span: span.start_time)
    # The whole list is known, so a tool span that sorts after the result can
    # still reach its step, and a batch read has no late span to fall back on.
    projection._expect_tool_spans(ordered)
    steps: list[AtifStep] = []
    for span in ordered:
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
    before the model call that receives its result. A call named there also
    holds its step until its span has been read, so a span that arrives after
    the result still lands on it. Any other ``execute_tool`` span that arrives
    once its step has been returned stands alone as a later ``system`` step,
    the shape of a result whose call was never read; those that remain at
    :meth:`finish` are written after every other step, so no step id moves.
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
        self._expected: set[str] = set(tool_statuses or {})
        self._outputs: dict[str, ToolSpanOutput] = {}
        self._answered: dict[str, tuple[AtifStep, AtifObservationResult]] = {}
        self._awaited: dict[str, AtifStep] = {}
        self._released_calls: set[str] = set()
        self._held: list[AtifStep] = []
        self._open: dict[str, list[AtifStep]] = {}
        self._calls: dict[str, AtifStep] = {}
        self._history: dict[str, list[str]] = {}
        self._instructions: set[tuple[str, ...]] = set()
        self._models: set[str] = set()
        self._step_count = 0
        self._omitted_parts = 0
        self._model_calls = 0
        self._usage_calls = 0
        self._prompt_tokens = Total()
        self._completion_tokens = Total()
        self._cached_tokens = Total()
        self._cost_usd = Total()

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

        self._read_tool_span(span)
        inputs = span.input_messages
        outputs = span.output_messages
        if not inputs and not outputs:
            return self._settled()

        lane = _lane(span)
        timestamp = _timestamp(span)
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

        introspection = span.attributes.introspection
        history = introspection.history if introspection else None
        declared = (
            history.new_messages.start
            if history and history.new_messages
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
        self._awaited.clear()
        # Spans without a single message stay refused, by :meth:`trajectory`.
        if self._step_count:
            for call_id, output in self._outputs.items():
                self._add_result(
                    call_id, output.content, output.details, output.timestamp
                )
        self._outputs.clear()
        return self._settled()

    @property
    def agent(self) -> AtifAgent:
        """The producing agent; its model is set only when one was observed."""
        return AtifAgent(
            name=self._agent_name or self._service_name or UNKNOWN,
            version=self._agent_version or UNKNOWN,
            model_name=(
                next(iter(self._models)) if len(self._models) == 1 else None
            ),
        )

    @property
    def final_metrics(self) -> AtifFinalMetrics:
        """The totals; one is set only when every model call reported it.

        A partial sum would read as the whole, so a metric some call left
        out stays unset. The read omits a zero, so two absences are known:
        a call that reported usage without cached tokens read none from the
        cache, and a call that used no tokens cost nothing.
        """
        calls = self._model_calls
        return AtifFinalMetrics(
            total_prompt_tokens=_whole(self._prompt_tokens.over(calls)),
            total_completion_tokens=_whole(
                self._completion_tokens.over(calls)
            ),
            total_cached_tokens=(
                _whole(self._cached_tokens.value)
                if calls and self._usage_calls == calls
                else None
            ),
            total_cost_usd=self._cost_usd.over(calls),
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
        waiting.update(id(step) for step in self._awaited.values())
        count = 0
        while count < len(self._held) and id(self._held[count]) not in waiting:
            count += 1
        settled, self._held = self._held[:count], self._held[count:]
        # Only the ids outlive a returned step, so a stream holds no history.
        released = {id(step) for step in settled}
        for call_id, (step, _) in list(self._answered.items()):
            if id(step) in released:
                del self._answered[call_id]
                self._released_calls.add(call_id)
        return settled

    def _close(self, lane: str) -> None:
        for step in self._open.pop(lane, []):
            for call in step.tool_calls or []:
                call_id = call.tool_call_id
                self._calls.pop(call_id, None)
                output = (
                    None
                    if call_id in self._answered
                    else self._outputs.pop(call_id, None)
                )
                if output is not None:
                    self._add_result(
                        call_id,
                        output.content,
                        output.details,
                        output.timestamp,
                        step=step,
                    )
                elif call_id in self._expected:
                    self._awaited[call_id] = step

    def _expect_tool_spans(self, spans: Iterable[GenAiSpan]) -> None:
        self._expected.update(filter(None, map(_tool_call_id, spans)))

    def _read_tool_span(self, span: GenAiSpan) -> None:
        call_id = _tool_call_id(span)
        gen_ai = span.attributes.gen_ai
        call = gen_ai.tool.call if gen_ai and gen_ai.tool else None
        if not call_id or call is None:
            return
        code = span.status.code if span.status else None
        if code in ("Ok", "Error"):
            self._tool_ok.setdefault(call_id, code == "Ok")
        self._expected.discard(call_id)
        awaited = self._awaited.pop(call_id, None)
        content, details = _tool_output(call.result)
        failed = self._tool_ok.get(call_id) is False
        if content is None and details is None and not failed:
            return
        output = ToolSpanOutput(_timestamp(span), content, details)
        answered = self._answered.get(call_id)
        if answered is not None:
            self._merge(call_id, answered[1], output)
        elif call_id in self._released_calls:
            # The step is already with the caller and cannot change.
            if details is not None or failed:
                self._add_result(call_id, content, details, output.timestamp)
        elif awaited is not None:
            self._add_result(
                call_id, content, details, output.timestamp, step=awaited
            )
        else:
            self._outputs[call_id] = output

    def _merge(
        self,
        call_id: str,
        result: AtifObservationResult,
        output: ToolSpanOutput,
    ) -> None:
        """Add a tool span read after its result to that result."""
        if result.content is None:
            result.content = output.content
        extra = {
            **(result.extra or {}),
            **self._result_extra(call_id, output.details),
        }
        result.extra = extra or None

    def _result_extra(
        self, call_id: str | None, details: Any
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if call_id is not None and self._tool_ok.get(call_id) is False:
            extra["is_error"] = True
        if details is not None:
            extra["details"] = details
        return extra

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
        output = self._outputs.pop(part.id, None) if part.id else None
        self._add_result(
            part.id,
            content,
            output.details if output else None,
            timestamp,
            step=self._calls.get(part.id) if part.id else None,
        )

    def _add_result(
        self,
        call_id: str | None,
        content: str | None,
        details: Any,
        timestamp: str,
        *,
        step: AtifStep | None = None,
    ) -> None:
        """Add one result to the step of its call, or as a step of its own."""
        extra = self._result_extra(call_id, details)
        if step is None:
            # ATIF only lets a result name a call of its own step, so a
            # result whose call was never read stands alone.
            result = AtifObservationResult(
                content=content,
                extra=(
                    {"tool_call_id": call_id, **extra}
                    if call_id
                    else extra or None
                ),
            )
            step = AtifStep(
                step_id=self._next_id(),
                timestamp=timestamp,
                source="system",
                message="",
                observation=AtifObservation(results=[result]),
            )
            self._append(step)
        else:
            result = AtifObservationResult(
                source_call_id=call_id, content=content, extra=extra or None
            )
            if step.observation is None:
                step.observation = AtifObservation(results=[])
            step.observation.results.append(result)
        if call_id:
            self._answered[call_id] = (step, result)

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
                self._answered.pop(call.tool_call_id, None)
                self._awaited.pop(call.tool_call_id, None)
                self._released_calls.discard(call.tool_call_id)

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
        self._model_calls += 1
        if usage is not None:
            self._usage_calls += 1
        self._prompt_tokens.add(prompt)
        self._completion_tokens.add(completion)
        self._cached_tokens.add(cached)
        unused = prompt == 0 and completion == 0
        self._cost_usd.add(0.0 if cost is None and unused else cost)
        return AtifMetrics(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached_tokens=cached,
            cost_usd=cost,
        )


@dataclass
class ToolSpanOutput:
    """What an ``execute_tool`` span said, until a result of its call takes it."""

    timestamp: str
    content: str | None
    details: Any


class Total:
    """A sum that remembers how many model calls reported a value."""

    def __init__(self) -> None:
        self.value = 0.0
        self.reported = 0

    def add(self, value: float | None) -> None:
        if value is not None:
            self.value += value
            self.reported += 1

    def over(self, calls: int) -> float | None:
        """The sum, when each of ``calls`` model calls reported a value."""
        return self.value if calls and self.reported == calls else None


def _whole(value: float | None) -> int | None:
    return None if value is None else int(value)


def _timestamp(span: GenAiSpan) -> str:
    return span.start_time.isoformat().replace("+00:00", "Z")


def _tool_call_id(span: GenAiSpan) -> str | None:
    gen_ai = span.attributes.gen_ai
    call = gen_ai.tool.call if gen_ai and gen_ai.tool else None
    return call.id if call else None


def _tool_output(result: Any) -> tuple[str | None, Any]:
    """``gen_ai.tool.call.result`` as ``(the tool's text, structured details)``.

    The attribute holds what the emitter wrote, and emitters stringify it. A
    string that holds no object or array is the tool's text and has no details.
    An envelope (:data:`TOOL_RESULT_ENVELOPE`) splits into its two halves, and
    any other value is the details itself.
    """
    if result is None:
        return None, None
    value = result
    if isinstance(result, str):
        try:
            value = json.loads(result)
        except ValueError:
            value = None
        if not isinstance(value, dict | list):
            return result or None, None
    if (
        isinstance(value, dict)
        and value.keys() <= TOOL_RESULT_ENVELOPE
        and ("details" in value or isinstance(value.get("content"), list))
    ):
        return _envelope_text(value.get("content")), value.get("details")
    return result if isinstance(result, str) else json.dumps(result), value


def _envelope_text(content: Any) -> str | None:
    """An envelope's content as ATIF's text; a non-text part stays as JSON."""
    if content is None or content == []:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") == "text"
        for part in content
    ):
        return "\n\n".join(str(part.get("text", "")) for part in content)
    return json.dumps(content)


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
