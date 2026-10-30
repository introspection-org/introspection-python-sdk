"""Browse a project's repositories — list them on the control plane, then
walk a directory, read a file and page recent commits through the data plane,
and ask for the Git provider token a sandbox clones with.

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
    IntrospectionAPIError,
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

        recent = client.repositories.commits(repo.id, limit=5).page().records
        for commit in recent:
            subject = commit.message.partition("\n")[0]
            print(f"  {commit.sha[:7]} {subject}")
        if recent:
            detail = client.repositories.commit(repo.id, recent[0].sha)
            print(f"  {recent[0].sha[:7]} changed {len(detail.files)} files")

        # #region docs:repository-access-token
        # Only a token issued to a sandbox gets a grant, for the runtime it
        # runs on; any other caller is refused, as this API key is.
        try:
            grant = client.repositories.access_token(
                repo.id, permissions={"contents": "read"}
            )
        except IntrospectionAPIError as exc:
            print(f"no Git provider token here: {exc.status_code}")
        else:
            # A SecretStr: `grant.token.get_secret_value()` is the password
            # for an HTTPS clone of `grant.repository` until it expires.
            print(f"{grant.provider} token for {grant.repository}")
            print(f"expires at {grant.expires_at}")
        # #endregion docs:repository-access-token

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
