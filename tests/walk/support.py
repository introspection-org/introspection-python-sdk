"""The walk's step runner, its run report, and the calls the SDK does not make.

Ported from the JS walk's ``tests/walk/support.ts``: ``settled()`` (poll
quietly, then read once through the recorded client), the OAuth follower and
the recipe push. There is no raw HTTP helper: every call the walk makes is an
SDK method, and a route the SDK lacks gets one before the walk calls it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import httpx2 as httpx

from introspection_sdk import NotFoundError

from .settings import Mode

__all__ = [
    "QuietTransport",
    "WalkReport",
    "follow_authorization",
    "has_complete_recording",
    "prepare_recipe",
    "push_recipe",
    "settled",
    "span_event_id",
    "walk_project_born",
]

T = TypeVar("T")


class QuietTransport(httpx.HTTPTransport):
    """The transport httpx2 had before VCR patched it, for the clients that
    poll: nothing they send is recorded, and nothing they send counts toward
    the order identical recorded requests are matched in."""

    handle_request = httpx.HTTPTransport.handle_request


@dataclass
class WalkReport:
    """The machine-readable run report the cross-SDK matrix reads."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    consumed: int = 0
    unconsumed: list[dict[str, str]] = field(default_factory=list)
    failed: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "sdk": "python",
            "steps": self.steps,
            "entries": {"total": self.total, "consumed": self.consumed},
            "unconsumed": self.unconsumed,
            # The cross-SDK matrix counts each SDK's raw calls; this walk
            # has no way to make one.
            "raw_calls": [],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_json(), indent=2) + "\n")


def walk_project_born(slug: str, prefix: str) -> int | None:
    """When a walk project was created, from its slug (see
    ``Walk.project_slug_prefix``); ``None`` for anyone else's project."""
    if not slug.startswith(prefix):
        return None
    try:
        return int(slug.removeprefix(prefix).split("-", 1)[0], 16)
    except ValueError:
        return None


def span_event_id(trace_id: str, span_id: str, label: str) -> UUID:
    """A UUIDv7-shaped id derived from the span an event annotates: the same on
    every replay (the span is recorded), new on every live run, where a fixed
    id would collide with the receipt a previous run left in the project."""
    digest = bytearray(
        hashlib.sha256(f"{trace_id}:{span_id}:{label}".encode()).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x70
    digest[8] = (digest[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(digest))


def _not_yet(poll: Callable[[], T]) -> T | None:
    # A conversation reads 404 until its first spans are ingested: not yet,
    # rather than gone.
    try:
        return poll()
    except NotFoundError:
        return None


def settled(
    mode: Mode,
    read: Callable[[], T],
    poll: Callable[[], T],
    done: Callable[[T], bool],
    *,
    label: str,
    timeout: float = 180.0,
    interval: float = 3.0,
) -> T:
    """Poll ``poll`` (a quiet client) until ``done``, then ``read`` once
    through the recorded client: that one read, in its terminal state, is
    what the recording carries (design doc §5). Replay only reads."""
    if mode != "replay":
        deadline = time.monotonic() + timeout
        while (value := _not_yet(poll)) is None or not done(value):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{label}: not done after {timeout}s: {value!r:.400}"
                )
            time.sleep(interval)
    final = read()
    if not done(final):
        raise AssertionError(
            f"{label}: the recorded read is not in its terminal state"
        )
    return final


CONTINUE_LINK = re.compile(r'<a\s+href="([^"]+)"[^>]*class="btn-primary"')
UPSTREAM_STATE = re.compile(r"searchParams\.set\('state',\s*'([^']+)'\)")


def _next_from_page(page: str, here: str) -> str | None:
    # The MCP reference server's consent page is one "Continue" link to its
    # mock upstream IdP; that IdP completes from a script that navigates to
    # its callback with a fixed code and the browser's user id, which the
    # walk fixes too, so the grant is the same subject every run.
    if link := CONTINUE_LINK.search(page):
        return link.group(1)
    upstream = UPSTREAM_STATE.search(page)
    if upstream and "/mock-upstream-idp/callback" in page:
        callback = httpx.URL(urljoin(here, "/mock-upstream-idp/callback"))
        return str(
            callback.copy_merge_params(
                {
                    "state": upstream.group(1),
                    "code": "mock-auth-code",
                    "userId": "sdk-walk-user",
                }
            )
        )
    return None


def follow_authorization(
    authorize_url: str,
    *,
    base_api_url: str,
    cookie: str,
    return_url: str,
    transport: httpx.BaseTransport | None = None,
) -> httpx.URL:
    """Complete an OAuth grant without a browser, as the MCP scenario
    harness does: follow the provider's redirects by hand and route the
    registered callback (a public name a local stack does not answer) to
    the Control Plane the walk talks to."""
    nxt = authorize_url
    with httpx.Client(transport=transport) as client:
        for _ in range(12):
            url = urlsplit(nxt)
            if url.path == "/v1/oauth/connections/callback":
                nxt = f"{base_api_url}{url.path}?{url.query}"
            if nxt.startswith(return_url):
                return httpx.URL(nxt)
            headers = (
                {"Cookie": f"intro_cp_session={cookie}"}
                if nxt.startswith(base_api_url)
                else {}
            )
            res = client.get(nxt, headers=headers)
            location = res.headers.get("location")
            if not location and res.status_code == 200:
                location = _next_from_page(res.text, nxt)
            if not location:
                raise AssertionError(
                    f"authorization stopped at {url.netloc}{url.path} with "
                    f"{res.status_code}: {res.text[:300]}"
                )
            nxt = urljoin(nxt, location)
    raise AssertionError("authorization did not reach the return URL")


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})},
    ).stdout.strip()


def prepare_recipe(url: str, ref: str, agent: str) -> Path:
    """The recipe the walk pushes, cloned at ``ref`` and checked to carry
    the walk's agent before anything is created. Live only."""
    target = Path(tempfile.mkdtemp(prefix="sdk-walk-recipe-"))
    try:
        _git(
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            ref,
            url,
            str(target),
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"cloning {url} failed: {exc.stderr.strip()}; set RECIPE_DIR to a "
            "recipe-harbor-mcp-agent checkout, or keep one beside this repository"
        ) from exc
    if not (target / "agents" / f"{agent}.yaml").exists():
        raise RuntimeError(f"{url} has no agents/{agent}.yaml on {ref}")
    return target


def push_recipe(checkout: Path, url: str, bearer: str) -> str:
    """Force-push the prepared recipe to the hosted ``main``. The bearer
    rides the environment as a git config, never argv. Live only; the git
    transport is a subprocess the recording cannot see."""
    env = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {bearer}",
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
    }
    sha = _git("-C", str(checkout), "rev-parse", "HEAD")
    deadline = time.monotonic() + 120
    while True:
        try:
            _git(
                "-C",
                str(checkout),
                "push",
                "--quiet",
                "--force",
                url,
                "HEAD:refs/heads/main",
                env=env,
            )
            return sha
        except subprocess.CalledProcessError as err:
            # The Data Plane provisions the hosted copy on its own schedule.
            if "not found" not in err.stderr.lower():
                raise
            if time.monotonic() > deadline:
                raise
            time.sleep(3)


def has_complete_recording(har: Path) -> bool:
    """Whether the recording reaches the walk's end: the teardown reads the
    walk's project it deleted (404), then the login's project."""
    if not har.exists():
        return False
    entries = json.loads(har.read_text())["log"]["entries"]
    if len(entries) < 2:
        return False
    gone, last = entries[-2:]
    project = re.compile(r"/v1/projects/[^/?]+$")
    return (
        gone["request"]["method"] == last["request"]["method"] == "GET"
        and gone["response"]["status"] == 404
        and last["response"]["status"] == 200
        and project.search(gone["request"]["url"]) is not None
        and project.search(last["request"]["url"]) is not None
    )
