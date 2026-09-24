"""Browse a project's repositories — list them on the control plane, then
walk a directory and read a file through the data plane.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.repositories

Optional env:
    INTROSPECTION_REPOSITORY    - repository slug (default: the first listed)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import (
    IntrospectionClient,
    NotFoundError,
    RepositoryFile,
)


def main() -> None:
    load_dotenv()
    if not os.getenv("INTROSPECTION_TOKEN"):
        sys.exit("Set INTROSPECTION_TOKEN to an Introspection API key.")

    client = IntrospectionClient()
    try:
        repos = client.repositories.list(
            slug=os.getenv("INTROSPECTION_REPOSITORY")
        )
        if not repos:
            print("no repositories linked to this project")
            return
        repo = repos[0]
        print(
            f"repository {repo.slug} ({repo.provider}) @ {repo.default_branch}"
        )

        # A Pager: iterating follows the `next` cursor across pages.
        for entry in client.repositories.contents(repo.id, limit=50):
            print(f"  {entry.type:9} {entry.path}")

        try:
            content = client.repositories.contents.get(repo.id, "README.md")
        except NotFoundError:
            print("no README.md at the default branch")
            return
        if isinstance(content, RepositoryFile):
            print(f"README.md at {content.commit_sha}: {content.size} bytes")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
