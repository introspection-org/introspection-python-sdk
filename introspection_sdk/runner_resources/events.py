"""`runner.events.*` namespace: read-only event reads.

Bound to a :class:`~introspection_sdk.runner.Runner` — every call targets
the runner's DP endpoint with its short-lived JWT. The surface is
read-only and mirrors ``runner.conversations``: one cursor-paginated list
read over the append-only ``otel_logs`` store. Every read names its
family — ``event_name`` is **required, exactly one** — so a page is
always homogeneous and each row validates into one member of the
discriminated :data:`~introspection_sdk.schemas.events.Event` union
(common envelope + nested typed ``payload``).

Three response representations share one request contract:

* JSON (default) — the standard cursor envelope
  (:class:`~introspection_sdk.schemas.pagination.Paginated`).
* Arrow (``format="arrow"``) — the same page as an Arrow IPC stream
  (envelope columns + a typed ``payload`` struct column) with pagination
  metadata on response headers, decoded back into the identical envelope
  (see :mod:`introspection_sdk.runner_resources._reads`).
* Columnar (:meth:`Events.arrow`) — the raw ``pyarrow.Table`` per page,
  for callers who want columns rather than models.

**Unknown-family tolerance:** rows whose ``event_name`` is outside the
SDK's known family set are skipped client-side (never raised), counted on
:data:`UNKNOWN_EVENT_SKIPS`, and debug-logged — so a new server-side
family doesn't break older SDKs.
"""

from __future__ import annotations

import logging

from introspection_sdk._async.runner_resources.events import (
    AsyncEvents,
)
from introspection_sdk._sync.runner_resources.events import (
    Events,
)
from introspection_sdk.runner_resources._events_common import (
    EVENT_ADAPTER,
    EVENT_PAYLOAD_JSON_FIELDS,
    UNKNOWN_EVENT_SKIPS,
    UnknownEventCounter,
    build_event_params,
    normalize_event_arrow_row,
    validate_event_page,
    validate_event_row,
    validate_single_event,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AsyncEvents",
    "EVENT_ADAPTER",
    "EVENT_PAYLOAD_JSON_FIELDS",
    "Events",
    "UNKNOWN_EVENT_SKIPS",
    "UnknownEventCounter",
    "build_event_params",
    "logger",
    "normalize_event_arrow_row",
    "validate_event_page",
    "validate_event_row",
    "validate_single_event",
]
