"""CP-bound namespaces hung off :class:`IntrospectionClient`."""

from introspection_sdk.resources.annotations import (
    Annotations,
    AsyncAnnotations,
)
from introspection_sdk.resources.api_keys import ApiKeys, AsyncApiKeys
from introspection_sdk.resources.applications import (
    ApplicationIdps,
    ApplicationKeys,
    Applications,
    ApplicationSecrets,
    AsyncApplicationIdps,
    AsyncApplicationKeys,
    AsyncApplications,
    AsyncApplicationSecrets,
)
from introspection_sdk.resources.connectors import (
    AsyncConnections,
    AsyncConnectors,
    Connections,
    Connectors,
)
from introspection_sdk.resources.credentials import (
    AsyncCredentials,
    Credentials,
)
from introspection_sdk.resources.endpoints import AsyncEndpoints, Endpoints
from introspection_sdk.resources.experiments import (
    AsyncExperimentHandle,
    AsyncExperiments,
    ExperimentHandle,
    Experiments,
)
from introspection_sdk.resources.integrations import (
    AsyncIntegrations,
    Integrations,
)
from introspection_sdk.resources.judges import AsyncJudges, Judges
from introspection_sdk.resources.members import AsyncMembers, Members
from introspection_sdk.resources.oidc import AsyncOidc, Oidc
from introspection_sdk.resources.organizations import (
    AsyncOrganizations,
    Organizations,
)
from introspection_sdk.resources.projects import (
    AsyncProjectPeerings,
    AsyncProjects,
    ProjectPeerings,
    Projects,
)
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
from introspection_sdk.resources.tags import AsyncTags, Tags
from introspection_sdk.resources.tokens import AsyncTokens, Tokens
from introspection_sdk.resources.variables import AsyncVariables, Variables
from introspection_sdk.runner_resources.automations import (
    AsyncAutomations,
    Automations,
)

__all__ = [
    "ApiKeys",
    "AsyncApiKeys",
    "ApplicationIdps",
    "ApplicationKeys",
    "Applications",
    "ApplicationSecrets",
    "AsyncApplicationIdps",
    "AsyncApplicationKeys",
    "AsyncApplications",
    "AsyncApplicationSecrets",
    "AsyncCredentials",
    "Credentials",
    "AsyncIntegrations",
    "Integrations",
    "AsyncJudges",
    "Judges",
    "AsyncOidc",
    "Oidc",
    "AsyncEndpoints",
    "Endpoints",
    "AsyncOrganizations",
    "Organizations",
    "AsyncTokens",
    "Tokens",
    "AsyncProjectPeerings",
    "AsyncProjects",
    "ProjectPeerings",
    "Projects",
    "AsyncVariables",
    "Variables",
    "Annotations",
    "Automations",
    "AsyncAnnotations",
    "AsyncAutomations",
    "AsyncConnections",
    "AsyncConnectors",
    "AsyncExperimentHandle",
    "AsyncExperiments",
    "AsyncMembers",
    "AsyncTags",
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
    "Tags",
    "Recipes",
    "Repositories",
    "RepositoryContents",
    "RepositoryMerges",
    "RuntimeHandle",
    "Runtimes",
]
