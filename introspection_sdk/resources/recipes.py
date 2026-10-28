"""``client.recipes`` — CP namespace for ``/v1/recipes``.

No handle subtype. A runner resolves the recipe it is running under; an
author pins one to a commit with :meth:`Recipes.create` and renames or
removes it with :meth:`Recipes.update` / :meth:`Recipes.delete`.
Recipes are immutable snapshots of a git repository at a specific commit;
runtimes / experiment arms refer to recipes by id.
"""

from __future__ import annotations

from introspection_sdk._async.resources.recipes import (
    AsyncRecipes,
)
from introspection_sdk._sync.resources.recipes import (
    Recipes,
)

__all__ = [
    "AsyncRecipes",
    "Recipes",
]
