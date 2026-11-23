"""The SDK's ATIF and GenAI modules re-export ``introspection_atif``."""

from __future__ import annotations

import importlib
from types import ModuleType

import introspection_atif.genai
import introspection_atif.genai_span
import introspection_atif.messages
import introspection_atif.projection
import introspection_atif.trajectory
import pytest

MOVED = [
    ("introspection_sdk.atif", introspection_atif.projection),
    ("introspection_sdk.atif_messages", introspection_atif.messages),
    ("introspection_sdk.schemas.atif", introspection_atif.trajectory),
    ("introspection_sdk.schemas.genai", introspection_atif.genai),
    ("introspection_sdk.schemas.genai_span", introspection_atif.genai_span),
]


@pytest.mark.parametrize(("name", "source"), MOVED)
def test_each_public_name_is_the_package_object(
    name: str, source: ModuleType
) -> None:
    module = importlib.import_module(name)
    assert sorted(module.__all__) == sorted(source.__all__)
    for attribute in source.__all__:
        assert getattr(module, attribute) is getattr(source, attribute)


def test_annotation_state_is_the_package_object() -> None:
    from introspection_atif.annotations import AnnotationState

    from introspection_sdk.schemas import AnnotationState as Reexported

    assert Reexported is AnnotationState
