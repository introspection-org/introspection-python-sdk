"""Everything the walk creates, found by its fixed names and removed.

Step 0 runs it to clear a crashed run, step 19 to clear this one, in the
same order as the JS walk's ``removeWalkResources``, so both read the same
recorded requests. Deleting is the owner's where a ``:delete`` scope is never
minted to an application (runtimes, recipes, experiments, repositories,
connectors); the member's Data Plane token does the rest.
"""

from __future__ import annotations

import contextlib

from introspection_sdk import IntrospectionClient, NotFoundError
from introspection_sdk.schemas.projects import Project
from introspection_sdk.schemas.tags import TagKind

from .settings import WALK

__all__ = ["remove_walk_resources"]


def remove_walk_resources(
    owner: IntrospectionClient,
    member: IntrospectionClient,
    project: Project,
    dp: IntrospectionClient | None = None,
) -> None:
    """Remove the walk's resources. Tasks and files are listed as the
    project's agent member (``dp``, the service account) where it exists: a
    member's own token lists only the tasks it owns."""
    _remove_data_plane(owner, member, dp or member, project)
    _remove_control_plane(owner, project)


def _remove_data_plane(
    owner: IntrospectionClient,
    member: IntrospectionClient,
    dp: IntrospectionClient,
    project: Project,
) -> None:
    for key in owner.api_keys.list(project=project.id):
        if key.name in (WALK.api_key_name, f"{WALK.api_key_name} (renamed)"):
            owner.api_keys.delete(key.id, project=project.id)
    for automation in member.automations.list():
        if automation.name == WALK.automation_name:
            member.automations.delete(automation.id)
    with contextlib.suppress(NotFoundError):
        member.tags.delete(TagKind.ACCESS, WALK.tag_name)
    for task in dp.tasks.list():
        if (task.metadata or {}).get("suite") == "walk":
            dp.tasks.delete(str(task.id))
    walk_files = [
        str(f.id)
        for f in dp.files.list()
        if f.name in (WALK.input_file_name, WALK.persona_file_name)
        or f.name.endswith(WALK.output_file_name)
    ]
    for share in dp.shares.list(resource_type="file"):
        if str(share.resource_id) in walk_files:
            dp.shares.delete(str(share.id))
    for file_id in walk_files:
        with contextlib.suppress(NotFoundError):
            dp.files.delete(file_id)


def _remove_control_plane(
    owner: IntrospectionClient, project: Project
) -> None:
    for experiment in owner.experiments.list(project=str(project.id)):
        if experiment.name in WALK.experiment_names:
            owner.experiments.delete(experiment.id, project=str(project.id))
    for runtime in owner.runtimes.list(
        project=str(project.id), runtime=WALK.runtime_slug
    ):
        # Deleting the group's live version takes its siblings with it.
        with contextlib.suppress(NotFoundError):
            owner.runtimes.delete(runtime.id, project=project.id)
    endpoints = owner.endpoints.list(
        project=project.id, mcp_server_id=WALK.mcp_server_id
    )
    for endpoint in endpoints.page().records:
        with contextlib.suppress(NotFoundError):
            owner.endpoints.delete(endpoint.id, project=project.id)
    for connector in owner.connectors.list(project=project.id).page().records:
        if connector.slug != WALK.connector_name:
            continue
        for connection in owner.connectors.connections.list(connector.id):
            owner.connectors.connections.revoke(connector.id, connection.id)
        owner.connectors.delete(connector.id, project=project.id)
    for variable in owner.variables.list(project=project.id):
        if variable.name == WALK.variable_name:
            owner.variables.delete(variable.id, project=project.id)
    for credential in owner.credentials.list(project=project.id):
        if credential.name == WALK.credential_name:
            owner.credentials.delete(credential.id, project=project.id)
    for repository in owner.repositories.list(
        project=project.id, slug=WALK.recipe_slug
    ):
        for recipe in owner.recipes.list(
            project=project.id, repository_id=repository.id
        ):
            owner.recipes.delete(recipe.id, project=project.id)
        owner.repositories.delete(repository.id, project=project.id)
    for application in owner.applications.list(project=project.id):
        if (
            application.name.startswith(WALK.application_name)
            or application.name == WALK.admin_name
        ):
            owner.applications.delete(application.id, project=project.id)
