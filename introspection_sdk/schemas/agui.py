"""AG-UI protocol schemas.

The Python SDK uses the official ``ag-ui-protocol`` package for event,
interrupt, and resume-entry models instead of maintaining local copies.
"""

from __future__ import annotations

from typing import Any

from ag_ui.core import (
    Event as AGUIEvent,
)
from ag_ui.core import (
    EventType,
    Interrupt,
    ResumeEntry,
    TextMessageChunkEvent,
    TextMessageContentEvent,
)
from pydantic import TypeAdapter

_AG_UI_EVENT_ADAPTER = TypeAdapter(AGUIEvent)


def validate_ag_ui_event(payload: Any) -> AGUIEvent:
    return _AG_UI_EVENT_ADAPTER.validate_python(payload)


__all__ = [
    "AGUIEvent",
    "EventType",
    "Interrupt",
    "ResumeEntry",
    "TextMessageChunkEvent",
    "TextMessageContentEvent",
    "validate_ag_ui_event",
]
