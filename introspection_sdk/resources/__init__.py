"""CP-bound namespaces hung off :class:`IntrospectionClient`."""

from introspection_sdk.resources.experiments import (
    AsyncExperiments,
    Experiments,
)
from introspection_sdk.resources.recipes import AsyncRecipes, Recipes
from introspection_sdk.resources.runtimes import AsyncRuntimes, Runtimes

__all__ = [
    "AsyncExperiments",
    "AsyncRecipes",
    "AsyncRuntimes",
    "Experiments",
    "Recipes",
    "Runtimes",
]
