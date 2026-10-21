"""``client.judges`` — CP namespace for ``/v1/judges``.

The judges a project's Recipes declare. Read and toggle only: a judge is
authored in its Recipe.
"""

from __future__ import annotations

from introspection_sdk._async.resources.judges import (
    AsyncJudges,
)
from introspection_sdk._sync.resources.judges import (
    Judges,
)

__all__ = [
    "AsyncJudges",
    "Judges",
]
