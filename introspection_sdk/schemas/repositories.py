"""Pydantic mirrors of CP ``/v1/repositories`` and DP repository contents
and commits.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so API additions don't break the SDK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Repository(_ApiModel):
    """A repository registered to a project — the Git source a recipe pins.

    ``provider`` and ``provisioning_status`` stay plain strings so a value
    the control plane adds later still reads.
    """

    id: UUID
    project_id: UUID
    integration_id: UUID | None = None
    url: str | None = None
    name: str | None = None
    slug: str | None = None
    provider: str = "github"
    default_branch: str = "main"
    provisioning_status: str = "pending"
    seed_template: str | None = None
    created_at: datetime
    pushed_at: datetime | None = None
    head_commit_sha: str | None = None
    is_recipe_source: bool = False


class RepositoryEntry(_ApiModel):
    """One entry of a directory listing."""

    name: str
    path: str
    type: Literal["file", "dir", "symlink", "submodule"]
    size: int = 0
    sha: str


class RepositoryDirectory(_ApiModel):
    """One page of a directory, read at ``commit_sha``.

    ``next`` is an opaque cursor; every page of one listing is read at the
    same commit.
    """

    type: Literal["dir"] = "dir"
    path: str
    commit_sha: str
    records: list[RepositoryEntry]
    count: int
    next: str | None = None


class RepositoryFile(_ApiModel):
    """A file's content at ``commit_sha``.

    ``content`` is empty and ``truncated`` is set when the file is larger
    than one read returns.
    """

    type: Literal["file"] = "file"
    name: str
    path: str
    size: int
    sha: str
    commit_sha: str
    encoding: Literal["utf-8", "base64"]
    content: str
    truncated: bool = False


RepositoryContent = Annotated[
    RepositoryDirectory | RepositoryFile, Field(discriminator="type")
]


class RepositoryCommitPerson(_ApiModel):
    """A commit's author or committer."""

    name: str
    email: str | None = None
    date: str | None = None


class RepositoryCommit(_ApiModel):
    """One commit of a history listing."""

    sha: str
    parents: list[str]
    message: str
    author: RepositoryCommitPerson
    committer: RepositoryCommitPerson


class RepositoryCommitFile(_ApiModel):
    """One file a commit changed."""

    filename: str
    status: Literal["added", "removed", "modified", "renamed"]
    additions: int
    deletions: int
    changes: int


class RepositoryCommitDetail(RepositoryCommit):
    """A commit with its changed files; ``patch`` is the whole commit as a
    unified git diff."""

    files: list[RepositoryCommitFile]
    patch: str


__all__ = [
    "Repository",
    "RepositoryCommit",
    "RepositoryCommitDetail",
    "RepositoryCommitFile",
    "RepositoryCommitPerson",
    "RepositoryContent",
    "RepositoryDirectory",
    "RepositoryEntry",
    "RepositoryFile",
]
