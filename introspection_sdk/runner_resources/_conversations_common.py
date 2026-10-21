"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.conversations`."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class ConversationExportParams(TypedDict, total=False):
    """Filters accepted by the complete conversation export route."""

    agent: str
    service_name: str
    operation_name: str | list[str]
    content: list[str]
    lookback_days: int
    start_date: str | datetime
    end_date: str | datetime
