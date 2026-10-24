"""The walk's step runner, its run report, and the calls the SDK does not make.

Ported from the JS walk's ``tests/walk/support.ts``: ``raw()`` (a documented
route the SDK has no method for, sent through the SDK's own HTTP client so
it is recorded and counted), ``settled()`` (poll quietly, then read once
through the recorded client), the OAuth follower and the recipe push.
"""

from __future__ import annotations

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

import httpx2 as httpx

from introspection_sdk._http import _HttpClient

from .settings import Mode

__all__ = [
    "QuietTransport",
    "Raw",
    "WalkReport",
    "follow_authorization",
    "has_complete_recording",
    "prepare_recipe",
    "push_recipe",
    "route",
    "settled",
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
    raw_calls: list[dict[str, str]] = field(default_factory=list)
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
            "raw_calls": self.raw_calls,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_json(), indent=2) + "\n")


ID_SEGMENT = re.compile(
    r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[0-9a-f]{40}|[0-9a-f]{16})(?=/|$)",
    re.I,
)


def route(path: str) -> str:
    """A request path as its route: each id segment becomes ``{id}``."""
    return ID_SEGMENT.sub("/{id}", path)


class Raw:
    """A documented route the SDK has no method for, called through the
    SDK's own HTTP client so it is recorded, counted and reported (design
    doc §3). Each use is an SDK gap the report lists."""

    def __init__(self, http: _HttpClient, report: WalkReport) -> None:
        self._http = http
        self._report = report

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        call = {"method": method, "path": route(path)}
        if call not in self._report.raw_calls:
            self._report.raw_calls.append(call)
        return self._http.request(method, path, **kwargs)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._call("GET", path, params=params)

    def post(
        self,
        path: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._call("POST", path, json=json, params=params)

    def patch(
        self, path: str, json: Any, params: dict[str, Any] | None = None
    ) -> Any:
        return self._call("PATCH", path, json=json, params=params)

    def delete(self, path: str, params: dict[str, Any] | None = None) -> None:
        self._call("DELETE", path, params=params, expect="empty")


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
        while not done(value := poll()):
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
    _git("clone", "--quiet", "--depth", "1", "--branch", ref, url, str(target))
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
    application it removed (404), then the login's project."""
    if not har.exists():
        return False
    entries = json.loads(har.read_text())["log"]["entries"]
    if len(entries) < 2:
        return False
    app, last = entries[-2:]
    return (
        app["response"]["status"] == 404
        and "/v1/applications/" in app["request"]["url"]
        and last["request"]["method"] == "GET"
        and re.search(r"/v1/projects/[^/?]+$", last["request"]["url"])
        is not None
    )
