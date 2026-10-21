"""``client.repositories`` — repository lookup (CP), contents, commits and
merges (DP).

A runner resolves the repository behind the recipe it runs, it does not
register one. Linking a repository to a project is a project-authoring act
and lives in the CLI.

Unlike the other CP lists, ``GET /v1/repositories`` answers a bare JSON
array rather than the cursor envelope, so :meth:`Repositories.list` returns
a ``list``. Contents are read on the data plane, which resolves ``ref`` to
one commit and reads every page of a listing at it. Commits page the
history from ``sha`` (the default branch when omitted). Merges mirror
GitHub's ``POST /repos/{owner}/{repo}/merges``.
"""

from __future__ import annotations

from introspection_sdk._async.resources.repositories import (
    AsyncRepositories,
    AsyncRepositoryContents,
    AsyncRepositoryMerges,
)
from introspection_sdk._sync.resources.repositories import (
    Repositories,
    RepositoryContents,
    RepositoryMerges,
)

__all__ = [
    "AsyncRepositories",
    "AsyncRepositoryContents",
    "AsyncRepositoryMerges",
    "Repositories",
    "RepositoryContents",
    "RepositoryMerges",
]
