"""CP-bound namespaces hung off :class:`IntrospectionClient`."""

from introspection_sdk.resources.annotations import (
    Annotations,
    AsyncAnnotations,
    AsyncProjectLabels,
    ProjectLabels,
)
from introspection_sdk.resources.connectors import (
    AsyncConnections,
    AsyncConnectors,
    Connections,
    Connectors,
)
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
    "Annotations",
    "AsyncAnnotations",
    "AsyncConnections",
    "AsyncConnectors",
    "AsyncExperimentHandle",
    "AsyncExperiments",
    "AsyncProjectLabels",
    "AsyncRecipes",
    "AsyncRuntimeHandle",
    "AsyncRuntimes",
    "Connections",
    "Connectors",
    "ExperimentHandle",
    "Experiments",
    "ProjectLabels",
    "Recipes",
    "RuntimeHandle",
    "Runtimes",
]
