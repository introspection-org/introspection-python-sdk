"""Field findings for one call site of one operation.

Presence and media type come first, because they hold whatever the
SDK's types say: a body sent to an operation that takes none fails even
when its type is unresolvable. A part whose type is unresolvable is a
warning, never a failure (see check).
"""

from __future__ import annotations

from typing import Any

from api_contract.call_types import NOT_LITERAL, SiteTypes, Slot
from api_contract.fields import Finding, Side, compare
from api_contract.reference import Shapes

__all__ = ["compare_site", "essence"]


def essence(media: str) -> str:
    """`application/x+json;version=1` -> `application/x+json`."""
    return media.split(";")[0].strip().lower()


def _media_entry(content: dict[str, Any], media: str) -> Any:
    if media in content:
        return content[media]
    return next(
        (v for k, v in content.items() if essence(k) == essence(media)), None
    )


def _body(
    ref: dict[str, Any], shapes: Shapes, body: Slot | None
) -> list[Finding]:
    if not shapes.body_media:
        if body is None:
            return []
        return [
            Finding(
                "extra",
                "body",
                f"the reference takes no body, SDK sends {body.media}",
            )
        ]
    if body is None:
        return (
            [Finding("missing", "body", "required body")]
            if shapes.body_required
            else []
        )
    if not any(essence(m) == essence(body.media) for m in shapes.body_media):
        return [
            Finding(
                "type",
                "body",
                f"reference takes {', '.join(shapes.body_media)}, "
                f"SDK sends {body.media}",
            )
        ]
    # A form body matches the reference's media type but carries no field
    # types to compare, like a non-JSON response.
    if body.not_json:
        return []
    if body.unresolved:
        return [Finding("unresolvable", "body", body.unresolved)]
    if shapes.body_schema is None or body.schema is None:
        return []
    return compare(
        Side(ref, shapes.body_schema), Side(body.schema, body.schema), "body"
    )


def _query(
    ref: dict[str, Any], shapes: Shapes, query: Slot | None
) -> list[Finding]:
    declared = shapes.query["properties"]
    if query is not None and query.unresolved:
        if not declared:
            return [
                Finding(
                    "extra",
                    "query",
                    "the reference takes no query parameters, SDK sends "
                    f"{query.unresolved}",
                )
            ]
        return [Finding("unresolvable", "query", query.unresolved)]
    if query is None or query.schema is None:
        # Nothing sent: every parameter the reference takes is missing, as
        # it would be from a sent query that leaves it out.
        return [Finding("missing", f"query.{name}") for name in declared]
    if not declared:
        return [
            Finding("extra", f"query.{name}")
            for name in query.schema.get("properties") or {}
        ]
    return compare(
        Side(ref, shapes.query), Side(query.schema, query.schema), "query"
    )


def _response(
    ref: dict[str, Any], shapes: Shapes, types: SiteTypes
) -> list[Finding]:
    response = types.response
    if response is None or response.not_json:
        return []
    if types.accept == NOT_LITERAL:
        return [
            Finding(
                "unresolvable", "response", "Accept header is not a literal"
            )
        ]
    media = types.accept or "application/json"
    entry = _media_entry(shapes.response, media)
    if not entry or not entry.get("schema"):
        declared = ", ".join(shapes.response)
        detail = (
            f"the reference declares {media} without a schema"
            if entry
            else f"the reference declares no {media} response"
            + (f" (only {declared})" if declared else "")
        )
        return [Finding("extra", "response", detail)]
    if response.unresolved:
        return [Finding("unresolvable", "response", response.unresolved)]
    if response.schema is None:
        return []
    return compare(
        Side(ref, entry["schema"]),
        Side(response.schema, response.schema),
        "response",
    )


def compare_site(
    ref: dict[str, Any], shapes: Shapes, types: SiteTypes
) -> list[Finding]:
    return [
        *_body(ref, shapes, types.body),
        *_query(ref, shapes, types.query),
        *_response(ref, shapes, types),
    ]
