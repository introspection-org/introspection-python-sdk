"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.events`."""

from __future__ import annotations

import logging
from typing import Any

# The logger of the public module, so log records keep their old name.
_logger = logging.getLogger("introspection_sdk.runner_resources.events")


class UnknownEventCounter:
    """Counts rows skipped because their family is unknown to this SDK."""

    def __init__(self) -> None:
        self.count = 0

    def increment(self, event_name: Any) -> None:
        self.count += 1
        _logger.debug(
            "skipping event row with unknown event_name %r "
            "(not in this SDK's typed family set; total skipped: %d)",
            event_name,
            self.count,
        )


#: Process-wide skip counter for unknown-family rows (observability hook).
UNKNOWN_EVENT_SKIPS = UnknownEventCounter()
