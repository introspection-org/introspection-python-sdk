"""A response model keeps a field the API adds and serialises it back."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from introspection_sdk.schemas.conversations import Conversation
from introspection_sdk.schemas.genai import InputMessage
from introspection_sdk.schemas.trajectory import TrajectoryUserRecord

CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (
        Conversation,
        {
            "id": "conv-1",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    ),
    (InputMessage, {"role": "user"}),
    (
        TrajectoryUserRecord,
        {"content": "hi", "timestamp": "2026-01-01T00:00:00Z"},
    ),
]


@pytest.mark.parametrize(
    ("model", "payload"), CASES, ids=[case[0].__name__ for case in CASES]
)
def test_unknown_field_is_kept_and_round_trips(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    added = "added_later"
    decoded = model.model_validate({**payload, added: {"n": 1}})

    assert decoded.model_extra == {added: {"n": 1}}
    assert getattr(decoded, added) == {"n": 1}
    dumped = decoded.model_dump(mode="json")
    assert dumped[added] == {"n": 1}
    assert model.model_validate(dumped) == decoded
