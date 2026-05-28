"""LangGraph subgraph tracing tests for IntrospectionCallbackHandler.

Phase 3a of docs/test-quality-audit-plan.md: when a LangGraph parent
graph invokes a subgraph, the callback handler must keep both under one
trace, propagate ``thread_id`` -> ``gen_ai.conversation.id`` through
subgraph boundaries, and preserve the span hierarchy.

These tests drive the callback handler directly (no HTTP) which is what
the rest of ``test_langchain_handler.py`` does — keeps the tests fast
and dependency-light while still exercising the parent/child run-id
plumbing that LangGraph relies on.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from introspection_sdk import AdvancedOptions
from tests.test_utils import (
    IncrementalIdGenerator,
    TimeGenerator,
    spans_to_dict,
)

HAS_LANGCHAIN_HANDLER = True
try:
    from introspection_sdk import IntrospectionCallbackHandler
    from introspection_sdk.otel.processors.langchain_callback_handler import (
        HAS_LANGCHAIN,
    )
except ImportError:
    HAS_LANGCHAIN_HANDLER = False
    if TYPE_CHECKING:
        from introspection_sdk import IntrospectionCallbackHandler
else:
    HAS_LANGCHAIN_HANDLER = HAS_LANGCHAIN

pytestmark = pytest.mark.skipif(
    not HAS_LANGCHAIN_HANDLER,
    reason="langchain-core not installed",
)


def _make_handler(
    exporter: InMemorySpanExporter,
) -> IntrospectionCallbackHandler:
    return IntrospectionCallbackHandler(
        token="test-token",
        advanced=AdvancedOptions(
            span_exporter=exporter,
            id_generator=IncrementalIdGenerator(),
            ns_timestamp_generator=TimeGenerator(),
        ),
    )


def test_subgraph_inherits_parent_trace():
    """A subgraph invocation must share the parent graph's trace id."""
    exporter = InMemorySpanExporter()
    handler = _make_handler(exporter)

    parent_run_id = uuid.uuid4()
    subgraph_run_id = uuid.uuid4()
    leaf_run_id = uuid.uuid4()

    # Parent graph starts.
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "hello"},
        run_id=parent_run_id,
        metadata={"thread_id": "thread-sub-1"},
        tags=["graph:step:0"],
    )

    # Parent invokes a subgraph node.
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "subgraph-input"},
        run_id=subgraph_run_id,
        parent_run_id=parent_run_id,
        metadata={"thread_id": "thread-sub-1"},
        tags=["graph:step:1", "langsmith:hidden"],
    )

    # A leaf node inside the subgraph emits a tool call.
    handler.on_tool_start(
        {"name": "weather_lookup"},
        "Tokyo",
        run_id=leaf_run_id,
        parent_run_id=subgraph_run_id,
        metadata={"thread_id": "thread-sub-1"},
    )
    handler.on_tool_end("Sunny 22C", run_id=leaf_run_id)

    handler.on_chain_end({"output": "subgraph-output"}, run_id=subgraph_run_id)
    handler.on_chain_end({"output": "done"}, run_id=parent_run_id)
    handler.force_flush()

    spans = spans_to_dict(
        exporter.get_finished_spans(), parse_json_attributes=False
    )
    assert spans, "expected at least one captured span"

    trace_ids = {span["context"]["trace_id"] for span in spans}
    assert len(trace_ids) == 1, (
        f"parent + subgraph + leaf must share one trace; got {trace_ids}"
    )

    # All spans inherit the conversation id from the parent's thread_id.
    convo_ids = {
        span["attributes"]["gen_ai.conversation.id"] for span in spans
    }
    assert convo_ids == {"thread-sub-1"}

    handler.shutdown()


def test_nested_subgraphs_three_levels():
    """Parent -> subgraph -> sub-subgraph: hierarchy and trace are preserved."""
    exporter = InMemorySpanExporter()
    handler = _make_handler(exporter)

    root = uuid.uuid4()
    mid = uuid.uuid4()
    leaf_graph = uuid.uuid4()
    leaf_tool = uuid.uuid4()

    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "root"},
        run_id=root,
        metadata={"thread_id": "thread-3lvl"},
    )
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "mid"},
        run_id=mid,
        parent_run_id=root,
        metadata={"thread_id": "thread-3lvl"},
    )
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "leaf-graph"},
        run_id=leaf_graph,
        parent_run_id=mid,
        metadata={"thread_id": "thread-3lvl"},
    )
    handler.on_tool_start(
        {"name": "compute"},
        "x*2",
        run_id=leaf_tool,
        parent_run_id=leaf_graph,
        metadata={"thread_id": "thread-3lvl"},
    )
    handler.on_tool_end("42", run_id=leaf_tool)
    handler.on_chain_end({"output": "leaf-done"}, run_id=leaf_graph)
    handler.on_chain_end({"output": "mid-done"}, run_id=mid)
    handler.on_chain_end({"output": "root-done"}, run_id=root)
    handler.force_flush()

    spans = spans_to_dict(
        exporter.get_finished_spans(), parse_json_attributes=False
    )

    trace_ids = {span["context"]["trace_id"] for span in spans}
    assert len(trace_ids) == 1

    # Find the leaf tool span and walk up — its parent chain should pass
    # through leaf_graph -> mid -> root (no shortcut to root).
    tool_span = next(
        s
        for s in spans
        if s.get("attributes", {}).get("gen_ai.tool.name") == "compute"
    )
    span_by_id = {s["context"]["span_id"]: s for s in spans}

    chain_depth = 0
    current = tool_span
    while current and current.get("parent"):
        current = span_by_id.get(current["parent"]["span_id"])
        if current is None:
            break
        chain_depth += 1
    assert chain_depth >= 3, (
        f"expected at least 3 ancestors for the leaf tool span, got "
        f"{chain_depth}"
    )

    handler.shutdown()


def test_two_parallel_subgraphs_keep_distinct_traces():
    """Two independent top-level graphs each run a subgraph; traces must not merge.

    Guards against a regression where the handler accidentally
    associates all subgraph spans with the most recently started parent.
    """
    exporter = InMemorySpanExporter()
    handler = _make_handler(exporter)

    parent_a = uuid.uuid4()
    sub_a = uuid.uuid4()
    parent_b = uuid.uuid4()
    sub_b = uuid.uuid4()

    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "A"},
        run_id=parent_a,
        metadata={"thread_id": "thread-A"},
    )
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "B"},
        run_id=parent_b,
        metadata={"thread_id": "thread-B"},
    )
    # Subgraphs start interleaved.
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "sub-A"},
        run_id=sub_a,
        parent_run_id=parent_a,
        metadata={"thread_id": "thread-A"},
    )
    handler.on_chain_start(
        {"name": "LangGraph"},
        {"input": "sub-B"},
        run_id=sub_b,
        parent_run_id=parent_b,
        metadata={"thread_id": "thread-B"},
    )
    handler.on_chain_end({"output": "sub-A-done"}, run_id=sub_a)
    handler.on_chain_end({"output": "sub-B-done"}, run_id=sub_b)
    handler.on_chain_end({"output": "A-done"}, run_id=parent_a)
    handler.on_chain_end({"output": "B-done"}, run_id=parent_b)
    handler.force_flush()

    spans = spans_to_dict(
        exporter.get_finished_spans(), parse_json_attributes=False
    )
    traces_by_conversation: dict[str, set[str]] = {}
    for span in spans:
        convo = span["attributes"]["gen_ai.conversation.id"]
        traces_by_conversation.setdefault(convo, set()).add(
            span["context"]["trace_id"]
        )

    # Each conversation should be exactly one trace, and the two
    # conversations must use different traces.
    assert (
        traces_by_conversation["thread-A"]
        != traces_by_conversation["thread-B"]
    )
    assert len(traces_by_conversation["thread-A"]) == 1
    assert len(traces_by_conversation["thread-B"]) == 1

    handler.shutdown()
