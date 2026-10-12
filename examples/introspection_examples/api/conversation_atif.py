"""Write a conversation as a Harbor ATIF trajectory.

Reads the GenAI spans of one conversation, projects them onto ATIF with
``spans_to_atif`` and writes ``trajectory.json``, the file Harbor reads from
a trial's agent directory. Without ``INTROSPECTION_CONVERSATION`` it takes
the newest conversation that holds a model call.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.conversation_atif

The projection itself needs no platform. To project spans you already hold
(a saved ``conversations.export_json`` result), pass the file instead; no
token is read:

        uv run python -m introspection_examples.api.conversation_atif spans.json

Optional env:
    INTROSPECTION_CONVERSATION  - conversation id (default: the newest with a model call)
    INTROSPECTION_ATIF_OUTPUT   - where to write (default trajectory.json)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.atif import spans_to_atif
from introspection_sdk.schemas import AtifStep, AtifTrajectory, GenAiSpanList

RECENT = 20


def read_trajectory(client: IntrospectionClient) -> AtifTrajectory | None:
    """The trajectory of the chosen conversation, or ``None`` without one."""
    chosen = os.getenv("INTROSPECTION_CONVERSATION")
    conversation_ids = (
        [chosen]
        if chosen
        else [
            conversation.id
            for conversation in client.conversations.list(limit=RECENT)
            .page()
            .records
        ]
    )
    for conversation_id in conversation_ids:
        spans = client.conversations.export_json(conversation_id).data
        try:
            return spans_to_atif(spans, session_id=conversation_id)
        except ValueError as error:
            # A conversation without a model call holds no message.
            print(f"skipping {conversation_id}: {error}")
    return None


def describe(step: AtifStep) -> str:
    line = f"  {step.step_id:>3} {step.source:6} {step.message[:60]!r}"
    for call in step.tool_calls or []:
        line += f"\n      call   {call.function_name}({call.tool_call_id})"
    for result in step.observation.results if step.observation else []:
        failed = " failed" if (result.extra or {}).get("is_error") else ""
        line += f"\n      result {result.source_call_id}{failed}"
    return line


def main() -> None:
    load_dotenv()
    if len(sys.argv) > 1:
        spans = GenAiSpanList.model_validate_json(
            Path(sys.argv[1]).read_text()
        ).data
        trajectory = spans_to_atif(spans)
    else:
        if not os.getenv("INTROSPECTION_TOKEN"):
            sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")
        client = IntrospectionClient()
        try:
            trajectory = read_trajectory(client)
        finally:
            client.shutdown()
        if trajectory is None:
            print("no recent conversation holds a model call")
            return

    agent = trajectory.agent
    print(f"{trajectory.schema_version} session {trajectory.session_id}")
    print(f"agent {agent.name} {agent.version} model {agent.model_name}")
    for step in trajectory.steps:
        print(describe(step))
    print(f"totals {trajectory.final_metrics}")
    if trajectory.notes:
        print(f"notes  {trajectory.notes}")

    output = Path(os.getenv("INTROSPECTION_ATIF_OUTPUT", "trajectory.json"))
    output.write_text(trajectory.model_dump_json(indent=2) + "\n")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
