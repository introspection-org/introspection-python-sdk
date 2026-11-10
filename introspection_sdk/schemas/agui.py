"""AG-UI protocol schemas.

The Python SDK uses the official ``ag-ui-protocol`` package for event,
interrupt, and resume-entry models instead of maintaining local copies.
"""

from __future__ import annotations

from typing import Any

from ag_ui.core import (
    AssistantMessage,
    CustomEvent,
    EventType,
    Interrupt,
    MessagesSnapshotEvent,
    ResumeEntry,
    RunErrorEvent,
    RunFinishedEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
)
from ag_ui.core import (
    Event as AGUIEvent,
)
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from introspection_sdk._strict_schema import strict_schema

_AG_UI_EVENT_ADAPTER = TypeAdapter(AGUIEvent)


class UnknownEvent(BaseModel):
    """An AG-UI event this SDK does not model: a new type, or a known type
    carrying a value it does not know. Every field the server sent is kept."""

    model_config = ConfigDict(extra="allow")

    type: str


#: What a run's stream yields: an event this SDK models, or an UnknownEvent.
AGUIStreamEvent = AGUIEvent | UnknownEvent


def validate_ag_ui_event(payload: Any) -> AGUIStreamEvent:
    """Decode one AG-UI event; one the SDK does not model is an
    :class:`UnknownEvent`, or raises under ``INTROSPECTION_STRICT_SCHEMA=1``."""
    try:
        return _AG_UI_EVENT_ADAPTER.validate_python(payload)
    except ValidationError:
        if strict_schema() or not isinstance(payload, dict):
            raise
        if not isinstance(payload.get("type"), str):
            raise
        return UnknownEvent.model_validate(payload)


__all__ = [
    "AGUIEvent",
    "AGUIStreamEvent",
    "AssistantMessage",
    "CustomEvent",
    "RunErrorEvent",
    "RunFinishedEvent",
    "EventType",
    "Interrupt",
    "MessagesSnapshotEvent",
    "ResumeEntry",
    "TextMessageChunkEvent",
    "TextMessageContentEvent",
    "UnknownEvent",
    "validate_ag_ui_event",
]
