"""Wire models for append-only span annotations."""

from typing import Literal

from introspection_atif.annotations import (
    AnnotationComment,
    AnnotationState,
    AnnotationTarget,
)

AnnotationInclude = Literal["comments"]
"""Optional expansions of a listed row, passed as a repeated ``include``
query param: ``comments`` sets each row's ``comments``."""

__all__ = [
    "AnnotationComment",
    "AnnotationInclude",
    "AnnotationState",
    "AnnotationTarget",
]
