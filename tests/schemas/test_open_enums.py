"""An enum value the API adds decodes as a plain ``str``, never an error.

A known value still decodes to the enum member, so ``is`` comparisons
against the member keep working.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import pkgutil
import types
import typing
from typing import Any, Literal

import pytest
from pydantic import BaseModel

import introspection_sdk.schemas as schemas
from introspection_sdk.schemas.files import File, FileType
from introspection_sdk.schemas.genai import InputMessage
from introspection_sdk.schemas.integrations import (
    Integration,
    IntegrationStatus,
)
from introspection_sdk.schemas.tags import Tag, TagKind
from introspection_sdk.schemas.task_commands import TaskCommand
from introspection_sdk.schemas.tasks import Task, TaskStatus

ORG = "019a0000-0000-7000-8000-000000000001"
PROJECT = "019a0000-0000-7000-8000-000000000002"
STAMP = "2026-01-01T00:00:00Z"

TASK = {
    "id": "019a0000-0000-7000-8000-000000000003",
    "org_id": ORG,
    "project_id": PROJECT,
    "created_at": STAMP,
    "updated_at": STAMP,
}
FILE = {
    **TASK,
    "name": "notes.md",
    "storage_path": "files/notes.md",
    "size_bytes": 1,
}
INTEGRATION = {
    "id": "019a0000-0000-7000-8000-000000000004",
    "org_id": ORG,
    "type": "github",
    "created_by_member_id": "019a0000-0000-7000-8000-000000000005",
}
COMMAND = {
    "id": "019a0000-0000-7000-8000-000000000006",
    "task_id": TASK["id"],
    "kind": "exec",
    "spec": {},
    "created_at": STAMP,
    "updated_at": STAMP,
}

CASES: list[tuple[type[BaseModel], dict[str, Any], str, Any, str]] = [
    (Task, TASK, "status", TaskStatus.RUNNING, "hibernating"),
    (File, FILE, "file_type", FileType.OTHER, "dataset"),
    (InputMessage, {}, "role", "assistant", "developer"),
    (
        Integration,
        INTEGRATION,
        "status",
        IntegrationStatus.ACTIVE,
        "suspended",
    ),
    (
        Tag,
        {"name": "team", "created_at": STAMP, "updated_at": STAMP},
        "kind",
        TagKind.ACCESS,
        "label",
    ),
]


@pytest.mark.parametrize(
    ("model", "base", "field", "known", "unknown"),
    CASES,
    ids=[f"{case[0].__name__}.{case[2]}" for case in CASES],
)
def test_known_value_is_the_member_and_unknown_is_the_string(
    model: type[BaseModel],
    base: dict[str, Any],
    field: str,
    known: Any,
    unknown: str,
) -> None:
    decoded = model.model_validate({**base, field: str(known)})
    assert getattr(decoded, field) == known
    assert type(getattr(decoded, field)) is type(known)

    opened = model.model_validate({**base, field: unknown})
    assert getattr(opened, field) == unknown
    assert type(getattr(opened, field)) is str


def test_an_unknown_command_status_counts_as_finished() -> None:
    assert not TaskCommand.model_validate(
        {**COMMAND, "status": "running"}
    ).is_terminal
    assert TaskCommand.model_validate(
        {**COMMAND, "status": "completed"}
    ).is_terminal
    assert TaskCommand.model_validate(
        {**COMMAND, "status": "timed_out"}
    ).is_terminal


# A field a tagged union routes on stays closed: widening it would let any
# shape match. These are the multi-value ones; single-value ``Literal``s
# (``object``, ``event_name``, a part's ``type``) are exempt by shape.
ROUTING_FIELDS = {
    ("genai", "ThinkingPart", "type"),
    ("genai", "BinaryPart", "type"),
    ("genai", "UrlPart", "type"),
}


def _closed(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return _closed(args[0])
    if origin in (typing.Union, types.UnionType):
        return str not in args and any(_closed(arg) for arg in args)
    if origin in (list, dict):
        return any(_closed(arg) for arg in args)
    if origin is Literal:
        return len(args) > 1
    return inspect.isclass(annotation) and issubclass(annotation, enum.Enum)


def _response_models() -> list[tuple[str, type[BaseModel]]]:
    found = []
    for info in pkgutil.iter_modules(schemas.__path__):
        module = importlib.import_module(f"{schemas.__name__}.{info.name}")
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseModel)
                and obj.__module__ == module.__name__
                and not name.startswith("_")
                and not name.endswith(("Request", "Create", "Update"))
                and obj.model_config.get("extra") != "forbid"
            ):
                found.append((info.name, obj))
    return found


def test_every_response_enum_field_is_open() -> None:
    closed = [
        f"{module}.{model.__name__}.{field}"
        for module, model in _response_models()
        for field, info in model.model_fields.items()
        if _closed(info.annotation)
        and (module, model.__name__, field) not in ROUTING_FIELDS
    ]
    assert closed == []
