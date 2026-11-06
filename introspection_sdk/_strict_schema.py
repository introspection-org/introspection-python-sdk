"""Opt-in strict decoding: report response fields this SDK does not model.

By default a response field the SDK's models do not name is tolerated (kept
by an ``extra="allow"`` model, dropped by the rest), so a server that adds a
field never breaks a client. With ``INTROSPECTION_STRICT_SCHEMA=1`` the same
response raises :class:`~introspection_sdk.SchemaDriftError`, naming the route
and every unmodelled field by its JSON path::

    /v1/tags: response fields this SDK does not model: $.records[0].color

The SDK's end-to-end walk runs strict, so a field the API adds shows up there
before a release ships without it. Keys in maps that are open by design are
never reported: a field typed as a ``dict`` (span ``resource``, endpoint
``metadata``, ...) and a model that sets ``open_schema = True`` (the
``gen_ai.*`` span attributes, the attribute families the SDK does not type,
and the GenAI message and part types).
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any, TypeVar, overload

from pydantic import AliasChoices, AliasPath, BaseModel, TypeAdapter

from introspection_sdk._errors import SchemaDriftError

__all__ = ["STRICT_SCHEMA_ENV", "decode", "note_response", "strict_schema"]

logger = logging.getLogger(__name__)

#: The environment variable that turns strict decoding on (``1``/``true``).
STRICT_SCHEMA_ENV = "INTROSPECTION_STRICT_SCHEMA"

M = TypeVar("M", bound=BaseModel)
T = TypeVar("T")

#: The route of the JSON response this context read last. The HTTP client
#: sets it, and the decode that follows names it in its error.
response_path: ContextVar[str | None] = ContextVar(
    "introspection_response_path", default=None
)


def strict_schema() -> bool:
    """Whether strict decoding is on, read from ``INTROSPECTION_STRICT_SCHEMA``."""
    value = os.environ.get(STRICT_SCHEMA_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def note_response(path: str) -> None:
    """Record the route of the JSON response about to be decoded."""
    response_path.set(path)


@overload
def decode(target: type[M], payload: Any) -> M: ...


@overload
def decode(target: TypeAdapter[T], payload: Any) -> T: ...


def decode(target: type[BaseModel] | TypeAdapter[Any], payload: Any) -> Any:
    """Validate a response ``payload``; under strict mode, report drift.

    ``target`` is a model class or a ``TypeAdapter``. Strict mode compares the
    decoded value with ``payload`` and raises
    :class:`~introspection_sdk.SchemaDriftError` when ``payload`` holds a key
    no model on its path names.
    """
    if isinstance(target, TypeAdapter):
        value = target.validate_python(payload)
    else:
        value = target.model_validate(payload)
    if strict_schema():
        check(value, payload, response_path.get())
    return value


def check(value: Any, payload: Any, path: str | None) -> None:
    """Raise when ``payload`` holds a key the decoded ``value`` does not model."""
    fields = unmodelled(value, payload)
    if fields:
        logger.debug(
            "response fields not modelled",
            extra={"path": path, "fields": fields},
        )
        raise SchemaDriftError(
            f"{path or 'response'}: response fields this SDK does not model: "
            + ", ".join(fields),
            path=path,
            fields=fields,
        )


def unmodelled(value: Any, payload: Any, at: str = "$") -> list[str]:
    """The JSON paths of the keys in ``payload`` that ``value`` does not model.

    Walks the decoded value beside its payload: a model's keys are matched to
    its fields by alias and name, a list item by index, a dict entry by key.
    Only a model reports keys; a ``dict`` field is open, and so is a model
    whose class sets ``open_schema = True``.
    """
    if isinstance(value, BaseModel) and isinstance(payload, dict):
        return _model_fields(value, payload, at)
    if isinstance(value, list | tuple) and isinstance(payload, list):
        found: list[str] = []
        for index, (item, raw) in enumerate(zip(value, payload, strict=False)):
            found += unmodelled(item, raw, f"{at}[{index}]")
        return found
    if isinstance(value, dict) and isinstance(payload, dict):
        found = []
        for key, raw in payload.items():
            if key in value:
                found += unmodelled(value[key], raw, f"{at}.{key}")
        return found
    return []


def _model_fields(
    value: BaseModel, payload: dict[Any, Any], at: str
) -> list[str]:
    names = _field_keys(type(value))
    open_schema = bool(getattr(type(value), "open_schema", False))
    found: list[str] = []
    for key, raw in payload.items():
        name = names.get(key)
        if name is None:
            if not open_schema:
                found.append(f"{at}.{key}")
            continue
        found += unmodelled(getattr(value, name), raw, f"{at}.{key}")
    return found


def _field_keys(model: type[BaseModel]) -> dict[str, str]:
    """Map every wire key a model accepts to the field it fills."""
    keys: dict[str, str] = {}
    for name, field in model.model_fields.items():
        keys[name] = name
        if field.alias:
            keys[field.alias] = name
        for alias in _aliases(field.validation_alias):
            keys[alias] = name
    return keys


def _aliases(alias: str | AliasPath | AliasChoices | None) -> list[str]:
    if alias is None:
        return []
    if isinstance(alias, str):
        return [alias]
    if isinstance(alias, AliasPath):
        first = alias.path[0]
        return [first] if isinstance(first, str) else []
    out: list[str] = []
    for choice in alias.choices:
        out += _aliases(choice)
    return out
