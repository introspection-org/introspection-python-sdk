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
from introspection_sdk.resources.members import AsyncMembers, Members
from introspection_sdk.resources.recipes import AsyncRecipes, Recipes
from introspection_sdk.resources.repositories import (
    AsyncRepositories,
    AsyncRepositoryContents,
    AsyncRepositoryMerges,
    Repositories,
    RepositoryContents,
    RepositoryMerges,
)
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
    "AsyncMembers",
    "AsyncProjectLabels",
    "AsyncRecipes",
    "AsyncRepositories",
    "AsyncRepositoryContents",
    "AsyncRepositoryMerges",
    "AsyncRuntimeHandle",
    "AsyncRuntimes",
    "Connections",
    "Connectors",
    "ExperimentHandle",
    "Experiments",
    "Members",
    "ProjectLabels",
    "Recipes",
    "Repositories",
    "RepositoryContents",
    "RepositoryMerges",
    "RuntimeHandle",
    "Runtimes",
]
