"""Contract tests for ``images`` (DP ``/v1/images``) and ``tasks.commands``
(DP ``/v1/tasks/{id}/commands``): the paths, list filters, the ``kind``-tagged
source and command bodies, and the wait cap."""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from introspection_sdk._errors import ConflictError
from introspection_sdk._http import _HttpClient
from introspection_sdk.runner_resources import (
    MAX_COMMAND_WAIT_SECONDS,
    AsyncImages,
    AsyncTasks,
    Images,
    Tasks,
)
from introspection_sdk.schemas.images import (
    ContextImageSource,
    ImageKind,
    ImageProvenance,
    ImageStatus,
    MirrorImageSource,
)
from introspection_sdk.schemas.task_commands import (
    DownloadCommand,
    ExecCommand,
    TaskCommandStatus,
    UploadCommand,
)
from introspection_sdk.schemas.tasks import TaskKind

from .conftest import (
    FILE_ID,
    REPOSITORY_ID,
    RUNTIME_ID,
    TASK_ID,
    FakeAPI,
    task_create_response,
)

NOW = "2026-10-21T12:00:00Z"
IMAGE_ID = "0199a1b2-0000-7000-8000-0000000000b1"
COMMAND_ID = "0199a1b2-0000-7000-8000-0000000000b2"
DIGEST = "sha256:" + "0" * 64
COMMANDS_PATH = f"/v1/tasks/{TASK_ID}/commands"
COMMAND_PATH = f"{COMMANDS_PATH}/{COMMAND_ID}"


def image_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": IMAGE_ID,
        "kind": "service",
        "name": "hello-mcp/mcp-server",
        "content_id": "c1",
        "source_kind": "mirror",
        "source": {"kind": "mirror", "reference": f"ghcr.io/x@{DIGEST}"},
        "build_platform": "linux/amd64",
        "status": "queued",
        "created_at": NOW,
        "updated_at": NOW,
        **over,
    }


def command_payload(**over: Any) -> dict[str, Any]:
    return {
        "id": COMMAND_ID,
        "task_id": TASK_ID,
        "kind": "exec",
        "spec": {"kind": "exec", "command": ["true"], "timeout_seconds": 300},
        "status": "queued",
        "created_at": NOW,
        "updated_at": NOW,
        **over,
    }


# --- images ----------------------------------------------------------


def test_image_list_sends_its_filters(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/images",
        json_body={"records": [image_payload()], "count": 1},
    )

    images = list(
        Images(fake_api.client()).list(
            kind=ImageKind.SERVICE,
            status="ready",
            name="hello-mcp/mcp-server",
            runtime_id=UUID(RUNTIME_ID),
            limit=5,
        )
    )

    assert [i.id for i in images] == [UUID(IMAGE_ID)]
    assert dict(fake_api.last_request.params) == {
        "kind": "service",
        "status": "ready",
        "name": "hello-mcp/mcp-server",
        "runtime_id": RUNTIME_ID,
        "limit": "5",
    }


def test_image_create_from_a_context_archive(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/images", status=201, json_body=image_payload())

    Images(fake_api.client()).create(
        name="hello-mcp/mcp-server",
        source=ContextImageSource(
            file_id=UUID(FILE_ID), platform="linux/arm64"
        ),
        provenance=ImageProvenance(
            service="mcp-server", repository_id=UUID(REPOSITORY_ID)
        ),
        scan=False,
    )

    assert fake_api.last_request.json() == {
        "name": "hello-mcp/mcp-server",
        "source": {
            "kind": "context",
            "file_id": FILE_ID,
            "platform": "linux/arm64",
        },
        "provenance": {
            "service": "mcp-server",
            "repository_id": REPOSITORY_ID,
        },
        "scan": False,
    }


def test_image_create_takes_a_tagged_dict(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/images", status=201, json_body=image_payload())

    created = Images(fake_api.client()).create(
        name="mirror",
        source={"kind": "mirror", "reference": f"ghcr.io/x@{DIGEST}"},
    )

    assert fake_api.last_request.json() == {
        "name": "mirror",
        "source": {"kind": "mirror", "reference": f"ghcr.io/x@{DIGEST}"},
    }
    assert created.status is ImageStatus.QUEUED
    assert created.pull_reference is None


def test_image_create_refuses_an_untagged_source(fake_api: FakeAPI):
    with pytest.raises(PydanticValidationError):
        Images(fake_api.client()).create(
            name="x", source={"reference": "ghcr.io/x"}
        )
    with pytest.raises(PydanticValidationError):
        MirrorImageSource.model_validate(
            {"kind": "mirror", "reference": "r", "file_id": FILE_ID}
        )
    assert fake_api.requests == []


def test_image_get_delete_and_pull_reference(fake_api: FakeAPI):
    path = f"/v1/images/{IMAGE_ID}"
    fake_api.add(
        "GET",
        path,
        json_body=image_payload(
            status="ready",
            image_ref="registry.test/sdk/mirror",
            image_digest=DIGEST,
        ),
    )
    fake_api.add("DELETE", path, status=204)
    images = Images(fake_api.client())

    image = images.get(UUID(IMAGE_ID))
    assert image.pull_reference == f"registry.test/sdk/mirror@{DIGEST}"
    images.delete(UUID(IMAGE_ID))
    assert fake_api.last_request.method == "DELETE"


def test_image_delete_while_baking_is_a_conflict(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/images/{IMAGE_ID}", status=409, json_body={})

    with pytest.raises(ConflictError):
        Images(fake_api.client()).delete(IMAGE_ID)


async def test_async_images_get(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/images/{IMAGE_ID}", json_body=image_payload())

    image = await AsyncImages(fake_api.async_client()).get(IMAGE_ID)

    assert image.kind is ImageKind.SERVICE


# --- task commands ---------------------------------------------------


@pytest.mark.parametrize(
    ("command", "body"),
    [
        (
            ExecCommand(command=["pytest", "-q"], cwd="/app", service="db"),
            {
                "kind": "exec",
                "command": ["pytest", "-q"],
                "cwd": "/app",
                "service": "db",
            },
        ),
        (
            UploadCommand(file_id=UUID(FILE_ID), path="/app/in.txt"),
            {"kind": "upload", "file_id": FILE_ID, "path": "/app/in.txt"},
        ),
        (
            DownloadCommand(path="/app/out.txt"),
            {"kind": "download", "path": "/app/out.txt"},
        ),
        (
            {"kind": "exec", "command": ["true"], "timeout_seconds": 5},
            {"kind": "exec", "command": ["true"], "timeout_seconds": 5},
        ),
    ],
)
def test_command_create_sends_the_tagged_body(
    fake_api: FakeAPI, command: Any, body: dict[str, Any]
):
    fake_api.add(
        "POST", COMMANDS_PATH, status=201, json_body=command_payload()
    )

    created = Tasks(fake_api.client()).commands.create(TASK_ID, command)

    assert fake_api.last_request.json() == body
    assert created.status is TaskCommandStatus.QUEUED
    assert not created.status.is_terminal


def test_command_create_refuses_a_shell_string(fake_api: FakeAPI):
    commands = Tasks(fake_api.client()).commands
    with pytest.raises(PydanticValidationError):
        commands.create(TASK_ID, {"kind": "exec", "command": "rm -rf /"})
    with pytest.raises(PydanticValidationError):
        commands.create(TASK_ID, {"kind": "shell", "command": ["true"]})
    assert fake_api.requests == []


def test_command_list_filters_by_status(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        COMMANDS_PATH,
        json_body={"records": [command_payload()], "count": 1},
    )

    listed = list(
        Tasks(fake_api.client()).commands.list(
            TASK_ID, status=TaskCommandStatus.RUNNING, limit=2
        )
    )

    assert [c.id for c in listed] == [UUID(COMMAND_ID)]
    assert dict(fake_api.last_request.params) == {
        "status": "running",
        "limit": "2",
    }


@pytest.mark.parametrize(
    ("asked", "sent"),
    [(None, None), (10, "10"), (60, str(MAX_COMMAND_WAIT_SECONDS)), (-1, "0")],
)
def test_command_get_caps_the_wait(
    fake_api: FakeAPI, asked: int | None, sent: str | None
):
    fake_api.add(
        "GET",
        COMMAND_PATH,
        json_body=command_payload(
            status="completed", exit_code=0, stdout="ok\n"
        ),
    )

    command = Tasks(fake_api.client()).commands.get(
        TASK_ID, UUID(COMMAND_ID), wait_seconds=asked
    )

    assert command.status.is_terminal
    assert command.exit_code == 0
    assert fake_api.last_request.params.get("wait_seconds") == sent


def test_wait_cap_stays_under_the_client_timeout():
    timeout = inspect.signature(_HttpClient).parameters["timeout"].default
    assert MAX_COMMAND_WAIT_SECONDS < timeout


async def test_async_command_get(fake_api: FakeAPI):
    fake_api.add("GET", COMMAND_PATH, json_body=command_payload())

    command = await AsyncTasks(fake_api.async_client()).commands.get(
        TASK_ID, COMMAND_ID, wait_seconds=120
    )

    assert command.kind == "exec"
    assert fake_api.last_request.params.get("wait_seconds") == "25"


# --- eval task create ------------------------------------------------


def test_task_create_sends_eval_kind_and_commands(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/tasks", status=201, json_body=task_create_response()
    )

    Tasks(fake_api.client()).create(
        prompt="run the suite", kind=TaskKind.EVAL, commands=True
    )

    assert fake_api.last_request.json() == {
        "prompt": "run the suite",
        "kind": "eval",
        "commands": True,
    }


def test_task_create_sends_compose_and_recipe_commit(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/tasks", status=201, json_body=task_create_response()
    )
    compose = {"services": {"db": {"image": "postgres:17"}}}

    Tasks(fake_api.client()).create(
        kind=TaskKind.EVAL,
        commands=True,
        compose=compose,
        recipe_git_commit_sha="a" * 40,
    )

    assert fake_api.last_request.json() == {
        "kind": "eval",
        "commands": True,
        "compose": compose,
        "recipe_git_commit_sha": "a" * 40,
    }


def test_task_create_omits_kind_and_commands_by_default(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/tasks", status=201, json_body=task_create_response()
    )

    Tasks(fake_api.client()).create(prompt="hi")

    assert fake_api.last_request.json() == {"prompt": "hi"}
