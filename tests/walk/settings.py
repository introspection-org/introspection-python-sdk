"""The walk's fixed names and the target it runs against.

The names the design doc fixes for every SDK's walk: every value the walk
puts in a request comes from a prior response or from here, so this SDK's
recording replays.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

__all__ = [
    "APPLICATION_SCOPES",
    "BOOTSTRAP_FILE",
    "RECORDINGS_DIR",
    "WALK",
    "Mode",
    "WalkSettings",
    "prompt",
    "second_turn",
    "walk_mode",
    "walk_settings",
]

Mode = Literal["record", "replay", "passthrough"]

#: Beside the HAR, wherever a record run writes it (``VCR_RECORDINGS_DIR``
#: redirects both, as ``POLLY_RECORDINGS_DIR`` does for the JS walk).
RECORDINGS_DIR = Path(
    os.environ.get(
        "VCR_RECORDINGS_DIR", Path(__file__).parent.parent / "recordings"
    )
)

#: What replay needs that no response carries: the login's project id.
BOOTSTRAP_FILE = "bootstrap.json"


@dataclass(frozen=True)
class Walk:
    sibling_suffix: str = "-walk"
    #: `sdk-walk-python-<unix time, hex>-<random>`: the SDK, so walks of
    #: different SDKs never sweep each other's project, and the time, which the
    #: projects list does not carry, so a sweep spares a run still going.
    project_slug_prefix: str = "sdk-walk-python-"
    #: A walk takes about a minute; one this old crashed before its teardown.
    stale_after_seconds: int = 3600
    application_name: str = "sdk-coverage-walk"
    tag_name: str = "walk"
    api_key_name: str = "walk"
    automation_name: str = "The walk's automation"
    experiment_names: tuple[str, ...] = (
        "The walk's experiment",
        "The walk's cancelled experiment",
    )
    credential_name: str = "WALK_SECRET"
    credential_secret: str = "walk-secret-value-0001"
    second_turn: str = "Reply with the single word done."
    variable_name: str = "WALK_MARKER"
    variable_value: str = "walk-marker-7f3a"
    connector_name: str = "hello-mcp"
    mcp_server_id: str = "hello-mcp"
    mcp_issuer: str = "https://example-server.modelcontextprotocol.io/"
    mcp_endpoint: str = "https://example-server.modelcontextprotocol.io/mcp"
    recipe_slug: str = "hello-mcp"
    runtime_slug: str = "hello-mcp"
    input_file_name: str = "walk-input.txt"
    input_file_text: str = "the walk's input file"
    output_file_name: str = "greeting.txt"
    #: The access step's people, customer members keyed ``user:walk-<name>``.
    personas: dict[str, list[str]] = field(
        default_factory=lambda: {
            "avery": ["group:platform"],
            "blake": [],
            "casey": ["group:platform"],
            "emery": [],
        }
    )
    group_tag: str = "group:platform"
    admin_name: str = "Drew"
    persona_file_name: str = "walk-avery-notes.txt"
    idp_issuer: str = "https://idp.walk.example.com"
    registered_token: str = "walk-registered-token-0001"
    api_endpoint_name: str = "walk-api"
    api_endpoint_host: str = "walk-api.example.com"
    image_name: str = "walk/busybox"
    # Digest-pinned, as a mirror must be; the copy may fail on a stack
    # with no egress, which the walk does not wait for.
    image_reference: str = (
        "docker.io/library/busybox@sha256:"
        "9ae97d36d26566ff84e8893c64a6dc4fe8ca6d1144bf5b87b2b85a32def253c7"
    )
    echo_message: str = "hello from the public MCP"
    echo_result: str = "Echo: hello from the public MCP"
    instruction: str = (
        "Call the `echo` tool from the declared `hello-mcp` MCP server with "
        "the message `hello from the public MCP`. Write the echoed value "
        "exactly, with no quotes or additional formatting, to "
        "`/workspace/outputs/greeting.txt`. Then run `echo $WALK_MARKER` in "
        "the shell and reply in one short sentence."
    )


WALK = Walk()

#: Every scope a service-account application may hold that the walk uses.
APPLICATION_SCOPES = [
    *("projects:read", "repositories:read", "repositories:write"),
    *("repositories:delete", "recipes:read", "recipes:write"),
    *("runtimes:read", "runtimes:write", "experiments:read"),
    *("experiments:write", "tasks:read", "tasks:write", "tasks:delete"),
    *("tasks:eval", "tasks:exec", "files:read", "files:write"),
    *("files:delete", "conversations:read", "events:read", "metrics:read"),
    *("shares:read", "shares:write", "shares:delete", "connectors:read"),
    *("connectors:write", "connections:read", "connections:write"),
    *("connections:delete", "automations:read", "automations:write"),
    *("annotations:read", "approvals:read", "approvals:write"),
    *("images:read", "images:write", "api_keys:read", "api_keys:write"),
    *("api_keys:delete", "applications:read", "applications:write"),
    *("applications:delete", "credentials:read", "credentials:write"),
    *("credentials:delete", "endpoints:read", "endpoints:write"),
    *("endpoints:delete", "variables:read", "variables:write"),
    *("variables:delete", "judges:read", "judges:write", "telemetry:write"),
]


@dataclass(frozen=True)
class WalkSettings:
    target: str
    #: Control Plane URL; the Data Plane URL comes from the token response.
    base_api_url: str
    #: The signed-in owner's Control Plane session, the bootstrap credential.
    cp_session: str
    #: The login's project: read only for the deployment the walk's own
    #: project is created on.
    bootstrap_project_id: str
    #: The project the walk creates, runs in and deletes: new on every live
    #: run, so each starts empty; replay sends the recorded one.
    project_slug: str
    dp_url: str
    #: Where the recipe is cloned from: a public URL, or a checkout on disk.
    recipe_repository_url: str
    recipe_git_ref: str
    #: The recipe agent: ``scripted`` on Compose, ``agent`` with a real model.
    agent: str


def walk_mode() -> Mode:
    """``VCR_MODE``, mirroring the JS walk's ``POLLY_MODE``."""
    mode = os.environ.get("VCR_MODE", "replay")
    if mode not in ("record", "replay", "passthrough"):
        raise ValueError(
            f"VCR_MODE={mode}: must be record, replay or passthrough"
        )
    return mode  # type: ignore[return-value]


def _recorded_bootstrap() -> dict[str, str]:
    path = RECORDINGS_DIR / "walk" / BOOTSTRAP_FILE
    return json.loads(path.read_text()) if path.exists() else {}


RECIPE_URL = "https://github.com/introspection-org/recipe-harbor-mcp-agent"
#: A checkout beside this repository: the recipe is private, so cloning it
#: needs GitHub credentials a local checkout does not.
SIBLING_RECIPE = (
    Path(__file__).resolve().parents[3] / "recipe-harbor-mcp-agent"
)


def _credentials_file() -> dict[str, str]:
    path = Path(
        os.environ.get(
            "INTROSPECTION_CREDENTIALS",
            Path.home() / ".introspection" / "credentials.json",
        )
    )
    return json.loads(path.read_text()) if path.exists() else {}


def walk_settings(mode: Mode) -> WalkSettings:
    """The target: the credentials ``introspection login`` writes, the
    environment over it. Replay needs none of them and gets fixed values."""
    if mode == "replay":
        return WalkSettings(
            target="compose",
            base_api_url="http://localhost:8000",
            cp_session="replay-session",
            bootstrap_project_id=_recorded_bootstrap().get("project_id", ""),
            project_slug=_recorded_bootstrap().get("project_slug", ""),
            dp_url="http://localhost:8002",
            recipe_repository_url=RECIPE_URL,
            recipe_git_ref="main",
            agent="scripted",
        )
    file, env = _credentials_file(), os.environ
    base_api_url = env.get("INTROSPECTION_BASE_API_URL", file.get("cp_url"))
    cp_session = env.get("INTROSPECTION_CP_SESSION", file.get("cp_session"))
    if not base_api_url or not cp_session:
        raise RuntimeError(
            f"the walk is in {mode} mode and has no Control Plane session: "
            "run `introspection login` or set INTROSPECTION_BASE_API_URL and "
            "INTROSPECTION_CP_SESSION"
        )
    project = env.get("INTROSPECTION_PROJECT_ID", file.get("project_id"))
    if not project:
        raise RuntimeError(
            "the walk runs in the login's project and the login names none: "
            "run `introspection login` and pick a project, or set "
            "INTROSPECTION_PROJECT_ID"
        )
    return WalkSettings(
        target=env.get("WALK_TARGET", "compose"),
        base_api_url=base_api_url,
        cp_session=cp_session,
        bootstrap_project_id=project,
        project_slug=(
            f"{WALK.project_slug_prefix}{int(time.time()):x}-{secrets.token_hex(2)}"
        ),
        dp_url=env.get("INTROSPECTION_DP_URL", file.get("dp_url", "")),
        recipe_repository_url=env.get(
            "RECIPE_DIR",
            env.get(
                "RECIPE_REPOSITORY_URL",
                str(SIBLING_RECIPE)
                if (SIBLING_RECIPE / ".git").exists()
                else RECIPE_URL,
            ),
        ),
        recipe_git_ref=env.get("RECIPE_GIT_REF", "main"),
        agent=env.get("WALK_AGENT", "scripted"),
    )


def _scripted_directive() -> str:
    """What the scripted model does on the instruction: the same three
    things a real model does, so the judge grades both alike."""
    directive = {
        "reply": (
            "Echoed the message through hello-mcp and wrote it to the "
            "outputs file."
        ),
        "tools": [
            {
                "name": "hello-mcp_echo",
                "arguments": {"message": WALK.echo_message},
            },
            {
                "name": "write",
                "arguments": {
                    "path": f"/workspace/outputs/{WALK.output_file_name}",
                    "content": WALK.echo_result,
                },
            },
            {"name": "bash", "arguments": {"command": "echo $WALK_MARKER"}},
        ],
    }
    return f"<<SCRIPT {json.dumps(directive, separators=(',', ':'))}>>"


def prompt(settings: WalkSettings) -> str:
    """The prompt for the target's agent."""
    if settings.agent == "scripted":
        return f"{WALK.instruction}\n\n{_scripted_directive()}"
    return WALK.instruction


def second_turn(settings: WalkSettings) -> str:
    """A second turn that needs no tool: the scripted agent is told it."""
    if settings.agent == "scripted":
        return f'{WALK.second_turn} <<SCRIPT {{"reply":"done"}}>>'
    return WALK.second_turn
