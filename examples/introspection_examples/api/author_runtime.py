"""Author a runtime: pin a recipe to a repository's commit, make a runtime
version from it, edit both, then delete them again.

Reads the project's first repository (or INTROSPECTION_REPOSITORY), its
branches and head commit, and the project's endpoints. When
INTROSPECTION_AUTHOR_WRITE=1 it also creates a recipe and a runtime version
from that commit, reads the version's MCP requirements, updates both, and
deletes the runtime and the recipe. Creating a runtime starts an image build;
deleting it right away cancels nothing that is already published.

Without INTROSPECTION_TOKEN or INTROSPECTION_PROJECT it prints a skip
message and exits 0, so the examples workflow can list it whether or not a
project is configured.

Run with:
    INTROSPECTION_TOKEN=intro_xxx   # a service account's or member's token
    INTROSPECTION_PROJECT=support   # project slug or id

        uv run -m introspection_examples.api.author_runtime

Optional env:
    INTROSPECTION_REPOSITORY     - repository slug (default: the first listed)
    INTROSPECTION_AUTHOR_WRITE   - 1 to create, update and delete a recipe and runtime
    INTROSPECTION_BASE_API_URL   - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.schemas.runtimes import RuntimeInclude


def main() -> None:
    load_dotenv()
    project = os.getenv("INTROSPECTION_PROJECT")
    if not os.getenv("INTROSPECTION_TOKEN") or not project:
        print(
            "skipping: set INTROSPECTION_TOKEN and INTROSPECTION_PROJECT "
            "(project slug or id) to run this example",
            file=sys.stderr,
        )
        return

    client = IntrospectionClient()
    try:
        repos = client.repositories.list(
            slug=os.getenv("INTROSPECTION_REPOSITORY")
        )
        if not repos:
            print("no repositories linked to this project")
            return
        repo = repos[0]

        # #region docs:author-runtime-read
        for branch in client.repositories.branches(repo.id, sort="recent"):
            print(f"  branch {branch.name} @ {branch.sha[:7]}")
        ref = repo.default_branch or "main"
        head = client.repositories.commits(repo.id, sha=ref).page().records[0]
        print(f"{repo.slug} {ref} is at {head.sha[:7]}")

        for endpoint in client.endpoints.list(project=project):
            print(
                f"  endpoint {endpoint.name} {endpoint.kind} {endpoint.host}"
            )
        # #endregion docs:author-runtime-read

        if os.getenv("INTROSPECTION_AUTHOR_WRITE") != "1":
            return

        # #region docs:author-runtime
        recipe = client.recipes.create(
            project=project,
            repository_id=repo.id,
            name=f"{repo.slug} (example)",
            git_ref=ref,
            git_commit_sha=head.sha,
        )
        client.recipes.update(
            recipe.id, project=project, description="made by an example"
        )

        # `slug` names the runtime group; an existing group gains this as
        # its next version.
        runtime = client.runtimes.create(
            project=project,
            recipe_id=recipe.id,
            name=f"{repo.slug}-example",
            slug=f"{repo.slug}-example",
        )
        print(f"runtime {runtime.id} build {runtime.image_build_status}")
        read = client.runtimes.get(
            runtime.id,
            project=project,
            include=[RuntimeInclude.MCP_REQUIREMENTS],
        )
        print(f"  needs MCP servers: {read.mcp_requirements}")
        client.runtimes.update(
            runtime.id, project=project, description="made by an example"
        )

        client.runtimes.delete(runtime.id, project=project)
        client.recipes.delete(recipe.id, project=project)
        print(f"created and deleted recipe {recipe.slug} and its runtime")
        # #endregion docs:author-runtime
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
