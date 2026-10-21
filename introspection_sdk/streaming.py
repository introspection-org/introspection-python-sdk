"""AG-UI event parsing over the task run SSE transport.

The HTTP response still uses Server-Sent Events as a transport detail, but
the public SDK surface yields validated AG-UI protocol events only.
"""

from __future__ import annotations

from introspection_sdk._async.streaming import (
    _parse_sse_async as _parse_sse_async,
)
from introspection_sdk._async.streaming import (
    parse_ag_ui_events_async,
)
from introspection_sdk._sync.streaming import _parse_sse as _parse_sse
from introspection_sdk._sync.streaming import (
    parse_ag_ui_events,
)

__all__ = [
    "parse_ag_ui_events",
    "parse_ag_ui_events_async",
]
