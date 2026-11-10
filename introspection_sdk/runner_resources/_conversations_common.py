"""Code shared by the sync and async twins in :mod:`introspection_sdk.runner_resources.conversations`."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

ConversationExportInclude = Literal["annotations", "comments"]
"""Optional expansions of an exported span, passed as a repeated ``include``
query param. ``annotations`` sets ``annotation`` on each annotated span;
``comments``, with it, fills that row's ``comments``. JSON lines only: the
server refuses it on the trajectory and Arrow representations."""


class ConversationExportParams(TypedDict, total=False):
    """Filters accepted by the complete conversation export route."""

    agent: str
    service_name: str
    operation_name: str | list[str]
    lookback_days: int
    start_date: str | datetime
    end_date: str | datetime
    include: list[ConversationExportInclude]
