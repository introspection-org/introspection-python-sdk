"""Everything the walk creates, found by its fixed names and removed.

Step 0 runs it to clear a crashed run, step 19 to clear this one, in the
same order as the JS walk's ``removeWalkResources``, so both read the same
recorded requests. Deleting is the owner's where a ``:delete`` scope is never
minted to an application (runtimes, recipes, experiments, repositories,
connectors); the member's Data Plane token does the rest.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from introspection_sdk import IntrospectionClient, NotFoundError
from introspection_sdk.schemas.projects import Project
from introspection_sdk.schemas.tags import TagKind

from .settings import WALK
from .support import Raw

__all__ = ["remove_walk_resources"]


def remove_walk_resources(
    owner: IntrospectionClient,
    member: IntrospectionClient,
    project: Project,
    raw: Callable[[IntrospectionClient, str], Raw],
    dp: IntrospectionClient | None = None,
) -> None:
    """Remove the walk's resources. Tasks and files are listed as the
    project's agent member (``dp``, the service account) where it exists: a
    member's own token lists only the tasks it owns."""
    _remove_data_plane(owner, member, dp or member, project)
    _remove_control_plane(owner, project, raw(owner, "cp"))


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
    owner: IntrospectionClient, project: Project, cp: Raw
) -> None:
    q = {"project": str(project.id)}
    for experiment in owner.experiments.list(project=str(project.id)):
        if experiment.name in WALK.experiment_names:
            owner.experiments.delete(experiment.id, project=str(project.id))
    for runtime in owner.runtimes.list(
        project=str(project.id), runtime=WALK.runtime_slug
    ):
        # Deleting the group's live version takes its siblings with it.
        # todo(sdk): no `runtimes.delete`; the route is documented.
        with contextlib.suppress(NotFoundError):
            cp.delete(f"/v1/runtimes/{runtime.id}", q)
    # todo(sdk): no `endpoints` namespace at all.
    endpoints = cp.get(
        "/v1/endpoints", {**q, "mcp_server_id": WALK.mcp_server_id}
    )
    for endpoint in endpoints["records"]:
        with contextlib.suppress(NotFoundError):
            cp.delete(f"/v1/endpoints/{endpoint['id']}", q)
    # todo(sdk): `connectors.list` / `connectors.delete` take no `project`.
    for connector in cp.get("/v1/connectors", q)["records"]:
        if connector["slug"] != WALK.connector_name:
            continue
        for connection in owner.connectors.connections.list(connector["id"]):
            owner.connectors.connections.revoke(connector["id"], connection.id)
        cp.delete(f"/v1/connectors/{connector['id']}", q)
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
            # todo(sdk): no `recipes.delete`.
            cp.delete(f"/v1/recipes/{recipe.id}", q)
        # todo(sdk): no `repositories.delete`.
        cp.delete(f"/v1/repositories/{repository.id}", q)
    for application in owner.applications.list(project=project.id):
        if (
            application.name.startswith(WALK.application_name)
            or application.name == WALK.admin_name
        ):
            owner.applications.delete(application.id, project=project.id)
