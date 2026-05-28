"""CP-bound namespaces hung off :class:`IntrospectionClient`."""

from introspection_sdk.resources.experiments import (
    ExperimentHandle,
    Experiments,
)
from introspection_sdk.resources.recipes import Recipes
from introspection_sdk.resources.runtimes import RuntimeHandle, Runtimes

__all__ = [
    "ExperimentHandle",
    "Experiments",
    "Recipes",
    "RuntimeHandle",
    "Runtimes",
]
