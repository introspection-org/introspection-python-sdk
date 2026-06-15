"""CP-bound namespaces hung off :class:`IntrospectionClient`."""

from introspection_sdk.resources.experiments import (
    AsyncExperimentHandle,
    AsyncExperiments,
    ExperimentHandle,
    Experiments,
)
from introspection_sdk.resources.recipes import AsyncRecipes, Recipes
from introspection_sdk.resources.runtimes import (
    AsyncRuntimeHandle,
    AsyncRuntimes,
    RuntimeHandle,
    Runtimes,
)

__all__ = [
    "AsyncExperimentHandle",
    "AsyncExperiments",
    "AsyncRecipes",
    "AsyncRuntimeHandle",
    "AsyncRuntimes",
    "ExperimentHandle",
    "Experiments",
    "Recipes",
    "RuntimeHandle",
    "Runtimes",
]
