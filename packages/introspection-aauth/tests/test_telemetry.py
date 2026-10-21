"""Federation emits the spans and records the data plane reads, carrying
identifiers and never a token."""

import logging
import re

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from .test_federation import inline
from .world import AS, World

#: The last words of a field the platform's log formatter drops
#: (introspection-cloud docs/design/logging-and-tracing.md).
REDACTED = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "key",
    "private_key",
    "credential",
    "credentials",
    "auth",
    "authorization",
    "cookie",
    "session",
    "email",
    "phone",
}
STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}

EXPORTER = InMemorySpanExporter()
PROVIDER = TracerProvider()
PROVIDER.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(PROVIDER)


async def test_a_federation_is_traced_and_logged_by_identifier(
    caplog: pytest.LogCaptureFixture,
):
    EXPORTER.clear()
    world = World()
    inline(world)
    mission = await world.approved_mission(budget=100_000)
    with caplog.at_level(logging.INFO, logger="introspection_aauth"):
        issued = await world.follow(await world.ask(mission, 60_000, aud=AS))
    assert issued.status_code == 200, issued.text

    names = {span.name for span in EXPORTER.get_finished_spans()}
    assert {
        "person_server.federate",
        "person_server.federate.metadata",
        "person_server.federate.request",
        "person_server.federate.delivery",
    } <= names

    recorded = [
        r
        for r in caplog.records
        if r.getMessage() == "federation outcome recorded"
    ]
    assert [r.__dict__["step"] for r in recorded] == ["issued"]
    decided = [
        r for r in caplog.records if r.getMessage() == "access request decided"
    ]
    assert [r.__dict__["decision"] for r in decided] == ["allow"]

    for record in caplog.records:
        for key in set(record.__dict__) - STANDARD:
            assert re.split(r"[._-]", key)[-1] not in REDACTED, key

    tokens = [world.agent_token, *mission.person_tokens.values()]
    for record in caplog.records:
        fields = " ".join(str(v) for v in record.__dict__.values())
        assert not any(token in fields for token in tokens)
