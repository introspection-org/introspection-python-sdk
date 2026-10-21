"""The project tag catalogue: the values a share, a member tag, or an annotation carries."""

from __future__ import annotations

from introspection_sdk._async.resources.tags import (
    AsyncTags,
)
from introspection_sdk._sync.resources.tags import (
    Tags,
)

__all__ = ["AsyncTags", "Tags"]
