"""Contract tests for ``client.repositories`` (CP) and its contents (DP)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx2 as httpx
import pytest

from introspection_sdk._errors import NotFoundError
from introspection_sdk.resources.repositories import (
    AsyncRepositories,
    Repositories,
)
from introspection_sdk.schemas.repositories import (
    RepositoryDirectory,
    RepositoryEntry,
    RepositoryFile,
)

from .conftest import PROJECT_ID, REPOSITORY_ID, FakeAPI

CONTENTS = f"/v1/repositories/{REPOSITORY_ID}/contents"
COMMIT = "c0ffee"


def repository(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": REPOSITORY_ID,
        "project_id": PROJECT_ID,
        "integration_id": None,
        "url": "https://git.example/acme/support.git",
        "name": "support",
        "slug": "support",
        "provider": "hosted",
        "default_branch": "main",
        "provisioning_status": "ready",
        "seed_template": "pi-agent",
        "created_at": "2026-09-01T00:00:00Z",
        "pushed_at": None,
        "head_commit_sha": COMMIT,
        "is_recipe_source": True,
    }
    body.update(over)
    return body


def entry(name: str, type_: str = "file") -> dict[str, Any]:
    return {"name": name, "path": name, "type": type_, "size": 1, "sha": "s"}


def directory(
    records: list[dict[str, Any]], next: str | None
) -> dict[str, Any]:
    return {
        "type": "dir",
        "path": "",
        "commit_sha": COMMIT,
        "records": records,
        "count": len(records),
        "next": next,
    }


def file_body(path: str = "agents/agent.yaml") -> dict[str, Any]:
    return {
        "type": "file",
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "size": 12,
        "sha": "f",
        "commit_sha": COMMIT,
        "encoding": "utf-8",
        "content": "name: agent\n",
        "truncated": False,
    }


def paged_directory(fake_api: FakeAPI) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "page-2":
            return httpx.Response(
                200, json=directory([entry("b.md")], next=None)
            )
        return httpx.Response(
            200, json=directory([entry("a", "dir")], next="page-2")
        )

    fake_api.add_handler("GET", CONTENTS, handler)


def repositories(fake_api: FakeAPI) -> Repositories:
    return Repositories(fake_api.client(), fake_api.client())


def async_repositories(fake_api: FakeAPI) -> AsyncRepositories:
    return AsyncRepositories(fake_api.async_client(), fake_api.async_client())


# --- control plane ----------------------------------------------------


def test_list_filters_by_project_and_slug(fake_api: FakeAPI) -> None:
    fake_api.add("GET", "/v1/repositories", json_body=[repository()])
    repos = repositories(fake_api).list(project="acme", slug="support")
    assert [r.id for r in repos] == [UUID(REPOSITORY_ID)]
    assert repos[0].provider == "hosted"
    assert dict(fake_api.last_request.params) == {
        "project": "acme",
        "slug": "support",
    }


def test_list_omits_unset_filters(fake_api: FakeAPI) -> None:
    fake_api.add("GET", "/v1/repositories", json_body=[])
    assert repositories(fake_api).list() == []
    assert dict(fake_api.last_request.params) == {}


def test_get_by_id(fake_api: FakeAPI) -> None:
    fake_api.add(
        "GET", f"/v1/repositories/{REPOSITORY_ID}", json_body=repository()
    )
    repo = repositories(fake_api).get(UUID(REPOSITORY_ID), project=PROJECT_ID)
    assert repo.head_commit_sha == COMMIT
    assert fake_api.last_request.params["project"] == PROJECT_ID


def test_get_missing_raises_not_found(fake_api: FakeAPI) -> None:
    with pytest.raises(NotFoundError):
        repositories(fake_api).get(UUID(REPOSITORY_ID))


# --- data plane contents ----------------------------------------------


def test_contents_pages_across_cursor(fake_api: FakeAPI) -> None:
    paged_directory(fake_api)
    entries = list(
        repositories(fake_api).contents(REPOSITORY_ID, ref="main", limit=1)
    )
    assert [e.name for e in entries] == ["a", "b.md"]
    assert all(isinstance(e, RepositoryEntry) for e in entries)
    first, second = fake_api.requests
    assert first.path == CONTENTS
    assert dict(first.params) == {"ref": "main", "limit": "1"}
    assert dict(second.params) == {
        "ref": "main",
        "limit": "1",
        "cursor": "page-2",
    }


def test_contents_page_keeps_directory_envelope(fake_api: FakeAPI) -> None:
    paged_directory(fake_api)
    page = repositories(fake_api).contents(REPOSITORY_ID).page()
    assert isinstance(page, RepositoryDirectory)
    assert page.commit_sha == COMMIT
    assert page.next == "page-2"


def test_contents_of_a_file_raises(fake_api: FakeAPI) -> None:
    fake_api.add(
        "GET", f"{CONTENTS}/README.md", json_body=file_body("README.md")
    )
    with pytest.raises(ValueError, match="is a file"):
        list(repositories(fake_api).contents(REPOSITORY_ID, "README.md"))


def test_get_file(fake_api: FakeAPI) -> None:
    fake_api.add("GET", f"{CONTENTS}/agents/agent.yaml", json_body=file_body())
    content = repositories(fake_api).contents.get(
        UUID(REPOSITORY_ID), "agents/agent.yaml", ref="v1"
    )
    assert isinstance(content, RepositoryFile)
    assert content.content == "name: agent\n"
    assert dict(fake_api.last_request.params) == {"ref": "v1"}


def test_get_root_directory(fake_api: FakeAPI) -> None:
    fake_api.add("GET", CONTENTS, json_body=directory([entry("a")], None))
    content = repositories(fake_api).contents.get(REPOSITORY_ID)
    assert isinstance(content, RepositoryDirectory)
    assert fake_api.last_request.path == CONTENTS


def test_path_is_encoded_per_segment(fake_api: FakeAPI) -> None:
    fake_api.add_handler(
        "GET",
        f"{CONTENTS}/docs/a b/50% #1?.md",
        lambda _r: httpx.Response(200, json=file_body("docs/a b/50% #1?.md")),
    )
    repositories(fake_api).contents.get(REPOSITORY_ID, "/docs/a b/50% #1?.md")
    assert fake_api.last_request.url.raw_path == (
        f"{CONTENTS}/docs/a%20b/50%25%20%231%3F.md".encode()
    )


def test_missing_path_raises_not_found(fake_api: FakeAPI) -> None:
    with pytest.raises(NotFoundError):
        repositories(fake_api).contents.get(REPOSITORY_ID, "nope")


# --- async twins --------------------------------------------------------


async def test_async_list_and_get(fake_api: FakeAPI) -> None:
    fake_api.add("GET", "/v1/repositories", json_body=[repository()])
    fake_api.add(
        "GET", f"/v1/repositories/{REPOSITORY_ID}", json_body=repository()
    )
    repos = async_repositories(fake_api)
    listed = await repos.list(slug="support")
    assert listed[0].slug == "support"
    assert fake_api.last_request.params["slug"] == "support"
    repo = await repos.get(REPOSITORY_ID, project="acme")
    assert repo.id == UUID(REPOSITORY_ID)
    assert fake_api.last_request.params["project"] == "acme"


async def test_async_contents_pages_across_cursor(fake_api: FakeAPI) -> None:
    paged_directory(fake_api)
    pager = async_repositories(fake_api).contents(REPOSITORY_ID)
    first = await pager
    assert first.next == "page-2"
    names = [e.name async for e in pager]
    assert names == ["a", "b.md"]
    assert fake_api.last_request.params["cursor"] == "page-2"


async def test_async_contents_of_a_file_raises(fake_api: FakeAPI) -> None:
    fake_api.add(
        "GET", f"{CONTENTS}/README.md", json_body=file_body("README.md")
    )
    with pytest.raises(ValueError, match="is a file"):
        await async_repositories(fake_api).contents(REPOSITORY_ID, "README.md")


async def test_async_get_file_encodes_path(fake_api: FakeAPI) -> None:
    fake_api.add_handler(
        "GET",
        f"{CONTENTS}/a b.md",
        lambda _r: httpx.Response(200, json=file_body("a b.md")),
    )
    content = await async_repositories(fake_api).contents.get(
        REPOSITORY_ID, "a b.md"
    )
    assert isinstance(content, RepositoryFile)
    assert (
        fake_api.last_request.url.raw_path == f"{CONTENTS}/a%20b.md".encode()
    )
