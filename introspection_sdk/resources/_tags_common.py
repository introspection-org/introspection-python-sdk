"""Code shared by the sync and async twins in :mod:`introspection_sdk.resources.tags`."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import TypeAdapter

from introspection_sdk._errors import ValidationError
from introspection_sdk.schemas.tags import (
    TagCreate,
    TagKind,
    TagUpdate,
)

_CREATE: TypeAdapter[TagCreate] = TypeAdapter(TagCreate)


def _path(kind: TagKind, name: str) -> str:
    # An access tag's name may contain `/`, so it is encoded even though the
    # API matches it as a path.
    return f"/v1/tags/{kind.value}/{quote(name, safe='')}"


def _create_body(tag: TagCreate) -> dict[str, object]:
    validated = _CREATE.validate_python(tag)
    return validated.model_dump(mode="json", exclude_none=True)


def _update_body(kind: TagKind, patch: TagUpdate) -> dict[str, object]:
    fields = patch.model_fields_set
    if not fields:
        raise ValidationError(
            "A tag update must name a color or a description",
            status_code=422,
            code="invalid_tag_update",
        )
    if kind is TagKind.ACCESS and "color" in fields:
        raise ValidationError(
            "An access tag has no color",
            status_code=422,
            code="invalid_tag_color",
        )
    # `exclude_unset` so an omitted description stays omitted: the API reads a
    # null as "clear it" and an absent key as "leave it".
    return patch.model_dump(mode="json", exclude_unset=True)
